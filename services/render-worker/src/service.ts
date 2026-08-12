import { createHash, randomBytes } from "node:crypto";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { chromium, type Browser, type Page } from "playwright";

import type { RenderBridgeRequest } from "../../../packages/audio-engine/src/index.js";
import { createBuiltinClickWav, LoopbackRenderServer, withTimeout } from "./runtime.js";
import {
  createRenderServiceServer,
  receiptFromBridge,
  resolveRenderOutputPath,
  type RenderExecutor,
  type RenderServiceRequest,
} from "./server.js";

class ChromiumRenderExecutor implements RenderExecutor {
  readonly #artifactRoot: string;
  readonly #loopback: LoopbackRenderServer;
  #browser: Browser | undefined;
  #page: Page | undefined;

  constructor(artifactRoot: string) {
    this.#artifactRoot = artifactRoot;
    const bundle = fileURLToPath(new URL("../dist/page-entry.js", import.meta.url));
    this.#loopback = new LoopbackRenderServer(bundle, createBuiltinClickWav());
  }

  async start(): Promise<void> {
    await this.#loopback.start();
    this.#browser = await chromium.launch({ headless: true });
    await this.#createPage();
  }

  async close(): Promise<void> {
    await this.#browser?.close();
    await this.#loopback.close();
  }

  async render(request: RenderServiceRequest, signal?: AbortSignal) {
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
    const outputPath = resolveRenderOutputPath(this.#artifactRoot, request.outputStorageKey);
    const token = randomBytes(16).toString("hex");
    this.#loopback.registerSink(token, outputPath, request.maximumBytes);
    const bridgeRequest: RenderBridgeRequest = {
      ...request.bridgeRequest,
      outputToken: token,
    };
    const abort = new Promise<never>((_, reject) => {
      signal?.addEventListener("abort", () => reject(new Error("RENDER_CLIENT_DISCONNECTED")), {
        once: true,
      });
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
      const bytes = await readFile(outputPath);
      return receiptFromBridge(
        request,
        bridge,
        createHash("sha256").update(bytes).digest("hex"),
      );
    } catch (error) {
      await this.#loopback.cancelSink(token);
      if (signal?.aborted || (error instanceof Error && error.message === "RENDER_TIMEOUT")) {
        await this.#page?.close();
        this.#page = undefined;
      }
      throw error;
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

const tempRoot = process.env.MOTIF_FORGE_TEMP_ROOT ?? "/tmp/motif-forge";
const port = Number(process.env.MOTIF_FORGE_RENDER_PORT ?? "8090");
const executor = new ChromiumRenderExecutor(tempRoot);
await executor.start();
const service = createRenderServiceServer(executor);
await service.start("0.0.0.0", port);
process.stdout.write(`render service ready on port ${port}\n`);

const shutdown = async (): Promise<void> => {
  await service.close();
  await executor.close();
};
process.once("SIGTERM", () => void shutdown());
process.once("SIGINT", () => void shutdown());
