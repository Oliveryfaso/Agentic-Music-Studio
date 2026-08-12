import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it, vi } from "vitest";

import {
  createRenderServiceServer,
  resolveRenderOutputPath,
  type RenderExecutor,
} from "../src/server.js";

describe("controlled render service", () => {
  it("resolves only job-scoped repository-relative outputs", async () => {
    const root = await mkdtemp(join(tmpdir(), "motif-forge-render-root-"));
    try {
      expect(
        resolveRenderOutputPath(root, "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav"),
      ).toBe(join(root, "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav"));
      for (const unsafe of ["/tmp/master.wav", "../master.wav", "tmp/other/master.wav"]) {
        expect(() => resolveRenderOutputPath(root, unsafe)).toThrow(
          "RENDER_OUTPUT_KEY_INVALID",
        );
      }
    } finally {
      await rm(root, { recursive: true });
    }
  });

  it("validates requests and exposes health without returning audio bytes", async () => {
    const receipt = {
        receiptVersion: "render-service-receipt.v1",
        requestId: "render-1",
        storageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav",
        sha256: "a".repeat(64),
        bytes: 4096,
        durationSeconds: 72,
        sampleRate: 48000,
        channels: 2,
        bitDepth: 24,
        peak: 0.5,
      } as const;
    const executor: RenderExecutor = {
      render: vi.fn(async () => receipt),
    };
    const server = createRenderServiceServer(executor);
    await server.start();
    try {
      const health = await fetch(`${server.origin}/health`);
      expect(await health.json()).toEqual({ status: "ready", concurrency: 1 });

      const invalid = await fetch(`${server.origin}/v1/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ requestVersion: "wrong" }),
      });
      expect(invalid.status).toBe(400);

      const accepted = await fetch(`${server.origin}/v1/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          requestVersion: "render-service-request.v1",
          requestId: "render-1",
          outputStorageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav",
          maximumBytes: 100000000,
          timeoutMs: 120000,
          bridgeRequest: {
            requestVersion: "render-bridge-request.v1",
            requestId: "render-1",
            outputToken: "0".repeat(32),
            outputBitDepth: 24,
            graph: {},
          },
        }),
      });
      const receipt = await accepted.json();
      expect(accepted.status).toBe(200);
      expect(receipt.sha256).toBe("a".repeat(64));
      expect(receipt.audioBytes).toBeUndefined();
    } finally {
      await server.close();
    }
  });

  it("rejects work while the sole render slot is occupied", async () => {
    let release: (() => void) | undefined;
    const render = vi.fn(
      () => new Promise<Awaited<ReturnType<RenderExecutor["render"]>>>((resolve) => {
        release = () => resolve({
          receiptVersion: "render-service-receipt.v1",
          requestId: "render-1",
          storageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav",
          sha256: "a".repeat(64),
          bytes: 4096,
          durationSeconds: 72,
          sampleRate: 48000,
          channels: 2,
          bitDepth: 24,
          peak: 0.5,
        });
      }),
    );
    const executor: RenderExecutor = {
      render,
    };
    const server = createRenderServiceServer(executor);
    await server.start();
    const payload = {
      requestVersion: "render-service-request.v1",
      requestId: "render-1",
      outputStorageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav",
      maximumBytes: 100000000,
      timeoutMs: 120000,
      bridgeRequest: {
        requestVersion: "render-bridge-request.v1",
        requestId: "render-1",
        outputToken: "0".repeat(32),
        outputBitDepth: 24,
        graph: {},
      },
    };
    try {
      const first = fetch(`${server.origin}/v1/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      await vi.waitFor(() => expect(render).toHaveBeenCalledTimes(1));
      const second = await fetch(`${server.origin}/v1/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...payload, requestId: "render-2" }),
      });
      expect(second.status).toBe(429);
      release?.();
      expect((await first).status).toBe(200);
    } finally {
      await server.close();
    }
  });

  it("maps render timeouts and internal execution faults to retryable HTTP statuses", async () => {
    const payload = {
      requestVersion: "render-service-request.v1",
      requestId: "render-failure",
      outputStorageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav",
      maximumBytes: 100000000,
      timeoutMs: 120000,
      bridgeRequest: {
        requestVersion: "render-bridge-request.v1",
        requestId: "render-failure",
        outputToken: "0".repeat(32),
        outputBitDepth: 24,
        graph: {},
      },
    };
    for (const [code, expectedStatus] of [
      ["RENDER_TIMEOUT", 504],
      ["RENDER_SERVICE_NOT_READY", 503],
      ["unexpected internal detail", 500],
    ] as const) {
      const server = createRenderServiceServer({
        render: vi.fn(async () => {
          throw new Error(code);
        }),
      });
      await server.start();
      try {
        const response = await fetch(`${server.origin}/v1/render`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        expect(response.status).toBe(expectedStatus);
        const body = await response.json();
        expect(body.errorCode).toBe(
          expectedStatus === 500 ? "RENDER_EXECUTION_FAILED" : code,
        );
      } finally {
        await server.close();
      }
    }
  });

  it("aborts execution when the render client disconnects", async () => {
    let observedSignal: AbortSignal | undefined;
    const server = createRenderServiceServer({
      render: vi.fn(
        (_request, signal) =>
          new Promise<Awaited<ReturnType<RenderExecutor["render"]>>>((_, reject) => {
            observedSignal = signal;
            signal?.addEventListener(
              "abort",
              () => reject(new Error("RENDER_CLIENT_DISCONNECTED")),
              { once: true },
            );
          }),
      ),
    });
    await server.start();
    const controller = new AbortController();
    const pending = fetch(`${server.origin}/v1/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        requestVersion: "render-service-request.v1",
        requestId: "disconnect",
        outputStorageKey: "jobs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/master.wav",
        maximumBytes: 100000000,
        timeoutMs: 120000,
        bridgeRequest: {
          requestVersion: "render-bridge-request.v1",
          requestId: "disconnect",
          outputToken: "0".repeat(32),
          outputBitDepth: 24,
          graph: {},
        },
      }),
    });
    try {
      await vi.waitFor(() => expect(observedSignal).toBeDefined());
      controller.abort();
      await expect(pending).rejects.toThrow();
      await vi.waitFor(() => expect(observedSignal?.aborted).toBe(true));
    } finally {
      await server.close();
    }
  });
});
