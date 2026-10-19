import { createHash, randomBytes } from "node:crypto";
import { createReadStream } from "node:fs";
import { fileURLToPath } from "node:url";

import { chromium, type Browser, type Page } from "playwright";

import type { RenderBridgeRequest, InstrumentBinding, InstrumentPackRef } from "../../../packages/audio-engine/src/index.js";
import type { ReviewedInstrumentCatalog } from "./instrument-catalog.js";
import { createBuiltinClickWav, LoopbackRenderServer, withTimeout } from "./runtime.js";
import {
  receiptFromBridge,
  resolveRenderOutputPath,
  type RenderExecutor,
  type RenderServiceRequest,
} from "./server.js";

export class ChromiumRenderExecutor implements RenderExecutor {
  readonly #artifactRoot: string;
  readonly #loopback: LoopbackRenderServer;
  #browser: Browser | undefined;
  #page: Page | undefined;
  readonly #catalog: ReviewedInstrumentCatalog | undefined;
  #packToken: string | undefined;

  constructor(artifactRoot: string, catalog?: ReviewedInstrumentCatalog) {
    this.#artifactRoot = artifactRoot;
    this.#catalog = catalog;
    const bundle = fileURLToPath(new URL("../dist/page-entry.js", import.meta.url));
    this.#loopback = new LoopbackRenderServer(bundle, createBuiltinClickWav());
  }

  async start(): Promise<void> {
    if(this.#catalog){
      this.#packToken=randomBytes(16).toString("hex");
      this.#loopback.registerInstrumentPack(this.#packToken,this.#catalog);
    }
    await this.#loopback.start();
    this.#browser = await chromium.launch({ headless: true });
    await this.#createPage();
  }

  instrumentPacks(): readonly InstrumentPackRef[] {
    const catalog=this.#catalog;
    return catalog ? [{packId:catalog.manifest.packId,packVersion:catalog.manifest.packVersion,
      manifestSha256:catalog.manifestSha256}] : [];
  }

  async close(): Promise<void> {
    await this.#browser?.close();
    await this.#loopback.close();
  }

  async render(request: RenderServiceRequest, signal?: AbortSignal) {
    if (signal?.aborted) throw new Error("RENDER_CLIENT_DISCONNECTED");
    if (this.#browser === undefined) {
      throw new Error("RENDER_SERVICE_NOT_READY");
    }
    if (this.#page === undefined || this.#page.isClosed()) {
      await this.#createPage();
    }
    const page = this.#page;
    if (page === undefined) {
      throw new Error("RENDER_SERVICE_NOT_READY");
    }
    // Abort events are not replayed to listeners attached after navigation.
    if (signal?.aborted) {
      await page.close();
      this.#page = undefined;
      throw new Error("RENDER_CLIENT_DISCONNECTED");
    }
    let instrumentBinding:InstrumentBinding|undefined;
    if(request.bridgeRequest.graph.schemaVersion === "audio-graph-spec.v2" || request.bridgeRequest.graph.schemaVersion === "audio-graph-spec.v3" || request.bridgeRequest.graph.schemaVersion === "audio-graph-spec.v4"){
      const catalog=this.#catalog, packToken=this.#packToken;
      if(!catalog || !packToken) throw new Error("INSTRUMENT_PACK_UNAVAILABLE");
      for(const track of request.bridgeRequest.graph.tracks){
        if(track.instrumentPack.packId!==catalog.manifest.packId || track.instrumentPack.packVersion!==catalog.manifest.packVersion)
          throw new Error("INSTRUMENT_PACK_UNAVAILABLE");
        // Manifest pin is supplied by explicit host review, never read from a request.
        if(track.instrumentPack.manifestSha256!==catalog.manifestSha256)
          throw new Error("INSTRUMENT_MANIFEST_HASH_MISMATCH");
      }
      instrumentBinding={manifest:catalog.manifest,manifestSha256:catalog.manifestSha256,
        baseUrl:`/instrument-packs/${packToken}`};
    }
    const outputPath = resolveRenderOutputPath(this.#artifactRoot, request.outputStorageKey);
    const token = randomBytes(16).toString("hex");
    this.#loopback.registerSink(token, outputPath, request.maximumBytes);
    const bridgeRequest: RenderBridgeRequest = {
      ...request.bridgeRequest,
      outputToken: token,
      ...(instrumentBinding ? {instrumentBinding} : {}),
    };
    let onAbort = (): void => undefined;
    const abort = new Promise<never>((_, reject) => {
      onAbort = () => reject(new Error("RENDER_CLIENT_DISCONNECTED"));
      signal?.addEventListener("abort", onAbort, { once: true });
      if (signal?.aborted) onAbort();
    });
    try {
      const bridge = await Promise.race([
        withTimeout(
          page.evaluate(async (value) => window.motifForgeRender(value), bridgeRequest),
          request.timeoutMs,
          async () => {
            await this.#page?.close();
            this.#page = undefined;
          },
        ),
        abort,
      ]);
      const digest = createHash("sha256");
      for await (const chunk of createReadStream(outputPath)) digest.update(chunk);
      return receiptFromBridge(request, bridge, digest.digest("hex"));
    } catch (error) {
      await this.#loopback.cancelSink(token);
      if (signal?.aborted || (error instanceof Error && error.message === "RENDER_TIMEOUT")) {
        await this.#page?.close();
        this.#page = undefined;
      }
      throw error;
    } finally {
      signal?.removeEventListener("abort", onAbort);
    }
  }

  async #createPage(): Promise<void> {
    if (this.#browser === undefined) {
      throw new Error("RENDER_SERVICE_NOT_READY");
    }
    this.#page = await this.#browser.newPage();
    await this.#page.goto(`${this.#loopback.origin}/render`, { waitUntil: "networkidle" });
  }
}
