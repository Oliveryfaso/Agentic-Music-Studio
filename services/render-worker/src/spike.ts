import { createHash, randomBytes, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir } from "node:fs/promises";
import { resolve } from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

import { chromium, type Browser, type Page } from "playwright";

import {
  buildThirtySecondSpikeGraph,
  type RenderBridgeReceipt,
  type RenderBridgeRequest,
} from "../../../packages/audio-engine/src/index.js";
import { createBuiltinClickWav, LoopbackRenderServer, withTimeout } from "./runtime.js";

type WavInfo = Readonly<{
  channels: number;
  sampleRate: number;
  bitDepth: number;
  frames: number;
  durationSeconds: number;
}>;

type PcmRepeatComparison = Readonly<{
  byteExact: boolean;
  comparedSamples: number;
  differentSamples: number;
  differentSampleRatio: number;
  maximumAbsoluteDeltaLsb: number;
}>;

function inspectWav(bytes: Uint8Array): WavInfo {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const text = (offset: number, length: number): string =>
    String.fromCharCode(...bytes.subarray(offset, offset + length));
  if (text(0, 4) !== "RIFF" || text(8, 4) !== "WAVE" || text(36, 4) !== "data") {
    throw new Error("RENDER_WAV_HEADER_INVALID");
  }
  const channels = view.getUint16(22, true);
  const sampleRate = view.getUint32(24, true);
  const bits = view.getUint16(34, true);
  const dataBytes = view.getUint32(40, true);
  const frames = dataBytes / (channels * (bits / 8));
  return { channels, sampleRate, bitDepth: bits, frames, durationSeconds: frames / sampleRate };
}

function comparePcm16Repeat(left: Uint8Array, right: Uint8Array): PcmRepeatComparison {
  if (left.byteLength !== right.byteLength || left.byteLength < 44) {
    return {
      byteExact: false,
      comparedSamples: 0,
      differentSamples: 0,
      differentSampleRatio: 1,
      maximumAbsoluteDeltaLsb: Number.POSITIVE_INFINITY,
    };
  }
  const leftView = new DataView(left.buffer, left.byteOffset, left.byteLength);
  const rightView = new DataView(right.buffer, right.byteOffset, right.byteLength);
  const comparedSamples = (left.byteLength - 44) / 2;
  let differentSamples = 0;
  let maximumAbsoluteDeltaLsb = 0;
  for (let offset = 44; offset < left.byteLength; offset += 2) {
    const delta = Math.abs(leftView.getInt16(offset, true) - rightView.getInt16(offset, true));
    if (delta > 0) {
      differentSamples += 1;
      maximumAbsoluteDeltaLsb = Math.max(maximumAbsoluteDeltaLsb, delta);
    }
  }
  return {
    byteExact: differentSamples === 0,
    comparedSamples,
    differentSamples,
    differentSampleRatio: differentSamples / comparedSamples,
    maximumAbsoluteDeltaLsb,
  };
}

async function currentContainerRssBytes(): Promise<number> {
  const entries = await readdir("/proc", { withFileTypes: true });
  let totalKiB = 0;
  for (const entry of entries) {
    if (!entry.isDirectory() || !/^\d+$/.test(entry.name)) {
      continue;
    }
    try {
      const status = await readFile(`/proc/${entry.name}/status`, "utf8");
      const match = status.match(/^VmRSS:\s+(\d+)\s+kB$/m);
      totalKiB += Number(match?.[1] ?? 0);
    } catch {
      // A short-lived Chromium helper can exit between enumeration and read.
    }
  }
  return totalKiB * 1024;
}

async function renderOne(
  page: Page,
  server: LoopbackRenderServer,
  outputPath: string,
  request: Omit<RenderBridgeRequest, "outputToken">,
  timeoutMs: number,
): Promise<RenderBridgeReceipt> {
  const outputToken = randomBytes(16).toString("hex");
  server.registerSink(outputToken, outputPath, 32 * 1024 * 1024);
  const bridgeRequest: RenderBridgeRequest = { ...request, outputToken };
  return withTimeout(
    page.evaluate(async (value) => window.motifForgeRender(value), bridgeRequest),
    timeoutMs,
    () => page.close(),
  );
}

async function main(): Promise<void> {
  const outputRoot = resolve(process.env.MOTIF_FORGE_SPIKE_OUTPUT_ROOT ?? "/tmp/motif-forge-spike");
  const runOutputRoot = resolve(outputRoot, `run-${randomUUID()}`);
  await mkdir(runOutputRoot, { recursive: true });
  const bundlePath = fileURLToPath(new URL("../dist/page-entry.js", import.meta.url));
  const server = new LoopbackRenderServer(bundlePath, createBuiltinClickWav());
  await server.start();
  let browser: Browser | undefined;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    await page.goto(`${server.origin}/render`, { waitUntil: "networkidle" });
    const graph = buildThirtySecondSpikeGraph();
    const masterPath = resolve(runOutputRoot, "spike-master.wav");
    const pluckStemPath = resolve(runOutputRoot, "spike-pluck-stem.wav");
    const padStemPath = resolve(runOutputRoot, "spike-pad-stem.wav");
    const repeatPath = resolve(runOutputRoot, "spike-master-repeat.wav");
    const masterStarted = performance.now();
    const master = await renderOne(
      page,
      server,
      masterPath,
      {
        requestVersion: "render-bridge-request.v1",
        requestId: "spike-master",
        outputBitDepth: 24,
        graph,
      },
      60_000,
    );
    const masterLatencyMs = performance.now() - masterStarted;
    let maximumObservedRssBytes = await currentContainerRssBytes();
    const pluckStemStarted = performance.now();
    const pluckStem = await renderOne(
      page,
      server,
      pluckStemPath,
      {
        requestVersion: "render-bridge-request.v1",
        requestId: "spike-pluck-stem",
        outputBitDepth: 24,
        graph,
        renderTrackIds: ["pluck"],
      },
      60_000,
    );
    const pluckStemLatencyMs = performance.now() - pluckStemStarted;
    maximumObservedRssBytes = Math.max(
      maximumObservedRssBytes,
      await currentContainerRssBytes(),
    );
    const padStemStarted = performance.now();
    const padStem = await renderOne(
      page,
      server,
      padStemPath,
      {
        requestVersion: "render-bridge-request.v1",
        requestId: "spike-pad-stem",
        outputBitDepth: 24,
        graph,
        renderTrackIds: ["pad"],
      },
      60_000,
    );
    const padStemLatencyMs = performance.now() - padStemStarted;
    maximumObservedRssBytes = Math.max(
      maximumObservedRssBytes,
      await currentContainerRssBytes(),
    );
    const repeatStarted = performance.now();
    const repeatedMaster = await renderOne(
      page,
      server,
      repeatPath,
      {
        requestVersion: "render-bridge-request.v1",
        requestId: "spike-master-repeat",
        outputBitDepth: 24,
        graph,
      },
      60_000,
    );
    const repeatLatencyMs = performance.now() - repeatStarted;
    maximumObservedRssBytes = Math.max(
      maximumObservedRssBytes,
      await currentContainerRssBytes(),
    );
    const masterBytes = await readFile(masterPath);
    const pluckStemBytes = await readFile(pluckStemPath);
    const padStemBytes = await readFile(padStemPath);
    const repeatBytes = await readFile(repeatPath);
    const masterInfo = inspectWav(masterBytes);
    const pluckStemInfo = inspectWav(pluckStemBytes);
    const padStemInfo = inspectWav(padStemBytes);
    const repeatComparison = comparePcm16Repeat(masterBytes, repeatBytes);
    const acceptance = {
      masterDurationValid: Math.abs(masterInfo.durationSeconds - 30) <= 1 / 48000,
      pluckStemDurationValid: Math.abs(pluckStemInfo.durationSeconds - 30) <= 1 / 48000,
      padStemDurationValid: Math.abs(padStemInfo.durationSeconds - 30) <= 1 / 48000,
      masterPeakValid: master.peak > 0.001 && master.peak <= 1,
      pluckStemPeakValid: pluckStem.peak > 0.001 && pluckStem.peak <= 1,
      padStemPeakValid: padStem.peak > 0.001 && padStem.peak <= 1,
      stemsDifferFromMaster:
        !masterBytes.equals(pluckStemBytes) && !masterBytes.equals(padStemBytes),
      stemsDifferFromEachOther: !pluckStemBytes.equals(padStemBytes),
      repeatPeakStable: Math.abs(repeatedMaster.peak - master.peak) <= 1 / 32768,
      repeatPcmStable:
        repeatComparison.maximumAbsoluteDeltaLsb <= 1 &&
        repeatComparison.differentSampleRatio <= 0.0001,
    };
    if (
      Object.values(acceptance).some((accepted) => !accepted)
    ) {
      throw new Error(`RENDER_SPIKE_ACCEPTANCE_FAILED:${JSON.stringify({ acceptance, repeatComparison })}`);
    }
    const report = {
      spikeVersion: "chromium-render-spike.v1",
      chromiumVersion: browser.version(),
      browserProcessReused: true,
      deterministicRepeat: acceptance.repeatPcmStable,
      repeatComparison,
      maximumObservedRssBytes,
      master: {
        ...master,
        latencyMs: masterLatencyMs,
        sha256: createHash("sha256").update(masterBytes).digest("hex"),
        wav: masterInfo,
      },
      pluckStem: {
        ...pluckStem,
        latencyMs: pluckStemLatencyMs,
        sha256: createHash("sha256").update(pluckStemBytes).digest("hex"),
        wav: pluckStemInfo,
      },
      padStem: {
        ...padStem,
        latencyMs: padStemLatencyMs,
        sha256: createHash("sha256").update(padStemBytes).digest("hex"),
        wav: padStemInfo,
      },
      repeatLatencyMs,
      outputRoot: runOutputRoot,
    };
    process.stdout.write(`${JSON.stringify(report)}\n`);
  } finally {
    await browser?.close();
    await server.close();
  }
}

await main();
