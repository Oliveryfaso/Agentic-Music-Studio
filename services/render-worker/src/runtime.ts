import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { createWriteStream } from "node:fs";
import { mkdir, readFile, rename, stat, unlink } from "node:fs/promises";
import { dirname } from "node:path";

type OutputSink = Readonly<{
  finalPath: string;
  maximumBytes: number;
}>;

export async function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
  onTimeout: () => Promise<void> | void,
): Promise<T> {
  let timeout: NodeJS.Timeout | undefined;
  const timer = new Promise<never>((_, reject) => {
    timeout = setTimeout(async () => {
      await onTimeout();
      reject(new Error("RENDER_TIMEOUT"));
    }, timeoutMs);
  });
  try {
    return await Promise.race([operation, timer]);
  } finally {
    if (timeout !== undefined) {
      clearTimeout(timeout);
    }
  }
}

export class LoopbackRenderServer {
  readonly #sinks = new Map<string, OutputSink>();
  readonly #pageBundlePath: string;
  readonly #sampleBytes: Uint8Array;
  readonly #server;
  #port = 0;

  constructor(pageBundlePath: string, sampleBytes: Uint8Array) {
    this.#pageBundlePath = pageBundlePath;
    this.#sampleBytes = sampleBytes;
    this.#server = createServer((request, response) => {
      void this.#handle(request, response);
    });
  }

  get origin(): string {
    if (this.#port === 0) {
      throw new Error("RENDER_SERVER_NOT_STARTED");
    }
    return `http://127.0.0.1:${this.#port}`;
  }

  async start(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      this.#server.once("error", reject);
      this.#server.listen(0, "127.0.0.1", () => resolve());
    });
    const address = this.#server.address();
    if (address === null || typeof address === "string") {
      throw new Error("RENDER_SERVER_ADDRESS_INVALID");
    }
    this.#port = address.port;
  }

  registerSink(token: string, finalPath: string, maximumBytes: number): void {
    if (!/^[a-f0-9]{32}$/.test(token) || this.#sinks.has(token)) {
      throw new Error("RENDER_OUTPUT_TOKEN_INVALID");
    }
    this.#sinks.set(token, { finalPath, maximumBytes });
  }

  async close(): Promise<void> {
    await new Promise<void>((resolve, reject) => {
      this.#server.close((error) => (error === undefined ? resolve() : reject(error)));
    });
  }

  async #handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    try {
      if (request.method === "GET" && request.url === "/render") {
        response.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
        response.end(
          '<!doctype html><meta charset="utf-8"><title>Motif Forge Render</title>' +
            '<script type="module" src="/page-entry.js"></script>',
        );
        return;
      }
      if (request.method === "GET" && request.url === "/page-entry.js") {
        const source = await readFile(this.#pageBundlePath);
        response.writeHead(200, { "Content-Type": "text/javascript; charset=utf-8" });
        response.end(source);
        return;
      }
      if (request.method === "GET" && request.url === "/assets/builtin-click.wav") {
        response.writeHead(200, {
          "Content-Type": "audio/wav",
          "Content-Length": this.#sampleBytes.byteLength,
          "Cache-Control": "public, max-age=3600, immutable",
        });
        response.end(this.#sampleBytes);
        return;
      }
      const match = request.url?.match(/^\/outputs\/([a-f0-9]{32})$/);
      if (request.method === "POST" && match?.[1] !== undefined) {
        const token = match[1];
        const sink = this.#sinks.get(token);
        if (sink === undefined) {
          response.writeHead(404).end();
          return;
        }
        this.#sinks.delete(token);
        await this.#receiveOutput(request, sink);
        response.writeHead(201).end();
        return;
      }
      response.writeHead(404).end();
    } catch {
      response.writeHead(500).end();
    }
  }

  async #receiveOutput(request: IncomingMessage, sink: OutputSink): Promise<void> {
    await mkdir(dirname(sink.finalPath), { recursive: true });
    const partialPath = `${sink.finalPath}.partial`;
    let received = 0;
    try {
      await new Promise<void>((resolve, reject) => {
        const output = createWriteStream(partialPath, { flags: "wx" });
        request.on("data", (chunk: Buffer) => {
          received += chunk.length;
          if (received > sink.maximumBytes) {
            request.destroy(new Error("RENDER_OUTPUT_TOO_LARGE"));
          }
        });
        request.once("error", reject);
        output.once("error", reject);
        output.once("finish", resolve);
        request.pipe(output);
      });
      const actual = (await stat(partialPath)).size;
      if (actual !== received || actual < 44 || actual > sink.maximumBytes) {
        throw new Error("RENDER_OUTPUT_SIZE_INVALID");
      }
      await rename(partialPath, sink.finalPath);
    } catch (error) {
      await unlink(partialPath).catch(() => undefined);
      throw error;
    }
  }
}

export function createBuiltinClickWav(sampleRate = 48000): Uint8Array {
  const frames = Math.round(sampleRate * 0.08);
  const dataBytes = frames * 2;
  const output = new ArrayBuffer(44 + dataBytes);
  const view = new DataView(output);
  const writeText = (offset: number, text: string): void => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  writeText(8, "WAVEfmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, dataBytes, true);
  for (let frame = 0; frame < frames; frame += 1) {
    const time = frame / sampleRate;
    const envelope = Math.exp(-time * 70);
    const signal = Math.sin(2 * Math.PI * 1800 * time) * envelope * 0.65;
    view.setInt16(44 + frame * 2, signal * 0x7fff, true);
  }
  return new Uint8Array(output);
}
