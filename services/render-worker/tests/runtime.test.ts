import { mkdtemp, readFile, rm, access } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import { createBuiltinClickWav, LoopbackRenderServer, withTimeout } from "../src/runtime.js";

describe("render worker runtime", () => {
  it("creates a deterministic PCM WAV for the built-in sampler", () => {
    const first = createBuiltinClickWav();
    const second = createBuiltinClickWav();
    expect(first).toEqual(second);
    expect(String.fromCharCode(...first.subarray(0, 4))).toBe("RIFF");
    expect(first.byteLength).toBeGreaterThan(44);
  });

  it("cancels a timed-out render exactly once", async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    const result = withTimeout(new Promise<never>(() => undefined), 25, cancel);
    const rejection = expect(result).rejects.toThrow("RENDER_TIMEOUT");
    await vi.advanceTimersByTimeAsync(25);
    await rejection;
    expect(cancel).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("accepts an output token exactly once and promotes atomically", async () => {
    const root = await mkdtemp(join(tmpdir(), "motif-forge-render-test-"));
    const outputPath = join(root, "render.wav");
    const server = new LoopbackRenderServer("/unused-page-bundle.js", createBuiltinClickWav());
    await server.start();
    try {
      const token = "a".repeat(32);
      const payload = Buffer.from(createBuiltinClickWav());
      server.registerSink(token, outputPath, payload.byteLength);

      const accepted = await fetch(`${server.origin}/outputs/${token}`, {
        method: "POST",
        body: payload,
      });
      expect(accepted.status).toBe(201);
      expect(await readFile(outputPath)).toEqual(payload);

      const replayed = await fetch(`${server.origin}/outputs/${token}`, {
        method: "POST",
        body: payload,
      });
      expect(replayed.status).toBe(404);
    } finally {
      await server.close();
      await rm(root, { recursive: true });
    }
  });

  it("cancels an unused sink and removes partial output", async () => {
    const root = await mkdtemp(join(tmpdir(), "motif-forge-render-cancel-test-"));
    const outputPath = join(root, "cancelled.wav");
    const partialPath = `${outputPath}.partial`;
    const server = new LoopbackRenderServer("/unused-page-bundle.js", createBuiltinClickWav());
    await server.start();
    try {
      const token = "b".repeat(32);
      server.registerSink(token, outputPath, 1024);
      await import("node:fs/promises").then(({ writeFile }) => writeFile(partialPath, "partial"));
      await server.cancelSink(token);

      await expect(readFile(partialPath)).rejects.toThrow();
      const response = await fetch(`${server.origin}/outputs/${token}`, {
        method: "POST",
        body: Buffer.from(createBuiltinClickWav()),
      });
      expect(response.status).toBe(404);
    } finally {
      await server.close();
      await rm(root, { recursive: true });
    }
  });
});


describe("bounded output cleanup", () => {
  it("removes an oversized upload and consumes its token", async () => {
    const root = await mkdtemp(join(tmpdir(), "motif-capacity-overflow-"));
    const output = join(root, "render.wav");
    const server = new LoopbackRenderServer("/unused.js", createBuiltinClickWav());
    await server.start();
    try {
      const token = "c".repeat(32);
      server.registerSink(token, output, 1024);
      await fetch(`${server.origin}/outputs/${token}`, {
        method: "POST", body: new Uint8Array(2048),
      }).catch(() => undefined);
      await vi.waitFor(async () => {
        await expect(access(`${output}.partial`)).rejects.toThrow();
        await expect(access(output)).rejects.toThrow();
      });
      const replay = await fetch(`${server.origin}/outputs/${token}`, {
        method: "POST", body: new Uint8Array(100),
      });
      expect(replay.status).toBe(404);
    } finally {
      await server.close();
      await rm(root, { recursive: true });
    }
  });
});


it("preserves the timeout label when page teardown rejects the render operation", async () => {
  vi.useFakeTimers();
  let rejectRender: (error: Error) => void = () => undefined;
  const operation = new Promise<never>((_, reject) => { rejectRender = reject; });
  const result = withTimeout(operation, 25, async () => {
    rejectRender(new Error("PAGE_TARGET_CLOSED"));
  });
  const rejection = expect(result).rejects.toThrow("RENDER_TIMEOUT");
  await vi.advanceTimersByTimeAsync(25);
  await rejection;
  vi.useRealTimers();
});
