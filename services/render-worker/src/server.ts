import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { isAbsolute, relative, resolve, sep } from "node:path";

import type {
  RenderBridgeReceipt,
  RenderBridgeRequest,
} from "../../../packages/audio-engine/src/index.js";

export type RenderServiceRequest = Readonly<{
  requestVersion: "render-service-request.v1";
  requestId: string;
  outputStorageKey: string;
  maximumBytes: number;
  timeoutMs: number;
  bridgeRequest: RenderBridgeRequest;
}>;

export type RenderServiceReceipt = Readonly<{
  receiptVersion: "render-service-receipt.v1";
  requestId: string;
  storageKey: string;
  sha256: string;
  bytes: number;
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  bitDepth: 16 | 24;
  peak: number;
}>;

export type RenderExecutor = Readonly<{
  render: (
    request: RenderServiceRequest,
    signal?: AbortSignal,
  ) => Promise<RenderServiceReceipt>;
}>;

function writeJson(response: ServerResponse, status: number, value: object): void {
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  response.end(JSON.stringify(value));
}

async function readJson(request: IncomingMessage, maximumBytes = 8 * 1024 * 1024): Promise<unknown> {
  const chunks: Buffer[] = [];
  let received = 0;
  for await (const chunk of request) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    received += bytes.length;
    if (received > maximumBytes) {
      throw new Error("RENDER_REQUEST_TOO_LARGE");
    }
    chunks.push(bytes);
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export function resolveRenderOutputPath(root: string, storageKey: string): string {
  const normalizedRoot = resolve(root);
  if (
    isAbsolute(storageKey) ||
    !/^jobs\/[0-9a-f-]{36}\/[A-Za-z0-9._-]+\.wav$/.test(storageKey)
  ) {
    throw new Error("RENDER_OUTPUT_KEY_INVALID");
  }
  const output = resolve(normalizedRoot, storageKey);
  const inside = relative(normalizedRoot, output);
  if (!inside || inside.startsWith(`..${sep}`) || isAbsolute(inside)) {
    throw new Error("RENDER_OUTPUT_KEY_INVALID");
  }
  return output;
}

function parseRequest(value: unknown): RenderServiceRequest {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("RENDER_SERVICE_REQUEST_INVALID");
  }
  const input = value as Record<string, unknown>;
  const bridge = input.bridgeRequest as Record<string, unknown> | undefined;
  if (
    input.requestVersion !== "render-service-request.v1" ||
    typeof input.requestId !== "string" ||
    input.requestId.length < 1 ||
    typeof input.outputStorageKey !== "string" ||
    !Number.isSafeInteger(input.maximumBytes) ||
    Number(input.maximumBytes) < 1024 ||
    Number(input.maximumBytes) > 2 * 1024 * 1024 * 1024 ||
    !Number.isSafeInteger(input.timeoutMs) ||
    Number(input.timeoutMs) < 1000 ||
    Number(input.timeoutMs) > 600000 ||
    bridge?.requestVersion !== "render-bridge-request.v1" ||
    bridge.requestId !== input.requestId ||
    (bridge.outputBitDepth !== 16 && bridge.outputBitDepth !== 24)
  ) {
    throw new Error("RENDER_SERVICE_REQUEST_INVALID");
  }
  return input as unknown as RenderServiceRequest;
}

export function createRenderServiceServer(executor: RenderExecutor) {
  let busy = false;
  let port = 0;
  const server = createServer((request, response) => {
    void (async () => {
      if (request.method === "GET" && request.url === "/health") {
        writeJson(response, 200, { status: "ready", concurrency: 1 });
        return;
      }
      if (request.method !== "POST" || request.url !== "/v1/render") {
        writeJson(response, 404, { errorCode: "RENDER_ROUTE_NOT_FOUND" });
        return;
      }
      if (busy) {
        writeJson(response, 429, { errorCode: "RENDER_CAPACITY_EXHAUSTED" });
        return;
      }
      try {
        const parsed = parseRequest(await readJson(request));
        busy = true;
        const cancellation = new AbortController();
        const cancel = (): void => cancellation.abort("RENDER_CLIENT_DISCONNECTED");
        request.once("aborted", cancel);
        response.once("close", () => {
          if (!response.writableEnded) cancel();
        });
        try {
          writeJson(response, 200, await executor.render(parsed, cancellation.signal));
        } finally {
          busy = false;
        }
      } catch (error) {
        const code = error instanceof Error ? error.message : "RENDER_SERVICE_REQUEST_INVALID";
        const requestErrors = new Set([
          "RENDER_REQUEST_TOO_LARGE",
          "RENDER_SERVICE_REQUEST_INVALID",
          "RENDER_OUTPUT_KEY_INVALID",
        ]);
        const status =
          code === "RENDER_TIMEOUT"
            ? 504
            : code === "RENDER_CLIENT_DISCONNECTED"
              ? 499
            : code === "RENDER_SERVICE_NOT_READY"
              ? 503
              : requestErrors.has(code)
                ? 400
                : 500;
        writeJson(response, status, {
          errorCode: status === 500 ? "RENDER_EXECUTION_FAILED" : code,
        });
      }
    })();
  });
  return {
    get origin(): string {
      if (port === 0) {
        throw new Error("RENDER_SERVICE_NOT_STARTED");
      }
      return `http://127.0.0.1:${port}`;
    },
    async start(host = "127.0.0.1", requestedPort = 0): Promise<void> {
      await new Promise<void>((resolveStart, reject) => {
        server.once("error", reject);
        server.listen(requestedPort, host, resolveStart);
      });
      const address = server.address();
      if (address === null || typeof address === "string") {
        throw new Error("RENDER_SERVICE_ADDRESS_INVALID");
      }
      port = address.port;
    },
    async close(): Promise<void> {
      await new Promise<void>((resolveClose, reject) => {
        server.close((error) => (error === undefined ? resolveClose() : reject(error)));
      });
    },
  };
}

export function receiptFromBridge(
  request: RenderServiceRequest,
  bridge: RenderBridgeReceipt,
  sha256: string,
): RenderServiceReceipt {
  return {
    receiptVersion: "render-service-receipt.v1",
    requestId: request.requestId,
    storageKey: request.outputStorageKey,
    sha256,
    bytes: bridge.bytes,
    durationSeconds: bridge.durationSeconds,
    sampleRate: bridge.sampleRate,
    channels: bridge.channels,
    bitDepth: bridge.bitDepth,
    peak: bridge.peak,
  };
}
