// Isolated headless render probe: no UI session, model, DB, Docker, or .env.
import { createHash, randomBytes } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import { execFileSync } from "node:child_process";
import { build } from "esbuild";
import { chromium } from "playwright";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const output = resolve(process.argv[2] ?? "");
if (process.argv.length !== 3) throw new Error("usage: node scripts/run_p0_render_baseline.mjs OUTPUT_ROOT");
// Only use the explicitly created symbolic evidence directory. Never overwrite a report.
await readFile(resolve(output, "symbolic-report.json"));
const reportPath = resolve(output, "render-report.json");
try { await readFile(reportPath); throw new Error("P0_RENDER_REPORT_EXISTS"); }
catch (e) { if (e.code !== "ENOENT") throw e; }
const bundleRoot = resolve(output, "bundles");
await mkdir(bundleRoot, { recursive: false });
await Promise.all([
  build({ absWorkingDir: repo, entryPoints: ["services/render-worker/src/page-entry.ts"], outfile: resolve(bundleRoot, "page-entry.js"), bundle: true, format: "esm", platform: "browser", target: "es2022" }),
  build({ absWorkingDir: repo, entryPoints: ["services/render-worker/src/runtime.ts"], outfile: resolve(bundleRoot, "runtime.mjs"), bundle: true, format: "esm", platform: "node", target: "node20" }),
  build({ absWorkingDir: repo, entryPoints: ["packages/audio-engine/src/spike-fixture.ts"], outfile: resolve(bundleRoot, "fixture.mjs"), bundle: true, format: "esm", platform: "node", target: "node20" }),
]);
const { LoopbackRenderServer, createBuiltinClickWav, withTimeout } = await import(resolve(bundleRoot, "runtime.mjs"));
const { buildThirtySecondSpikeGraph } = await import(resolve(bundleRoot, "fixture.mjs"));
const server = new LoopbackRenderServer(resolve(bundleRoot, "page-entry.js"), createBuiltinClickWav());
let browser;
let sampler;
let phase = "startup";
const memory = [];
function sample() {
  try {
    const rows = execFileSync("ps", ["-axo", "pid=,ppid=,rss="], { encoding: "utf8" }).trim().split("\n").map((s) => s.trim().split(/\s+/).map(Number));
    const selected = new Set([process.pid]);
    for (let pass = 0; pass < 12; pass++) for (const [pid, parent] of rows) if (selected.has(parent)) selected.add(pid);
    const rss = rows.filter(([pid]) => selected.has(pid)).reduce((sum, [, , value]) => sum + value, 0) * 1024;
    memory.push({ phase, elapsedMs: Math.round(performance.now()), processTreeRssBytes: rss });
  } catch { /* Unsupported sampling is reported rather than invented. */ }
}
const runs = [];
function comparePcm24(left, right) {
  if (left.length !== right.length) throw new Error("P0_REPEAT_LENGTH_MISMATCH");
  let maximum = 0;
  let changed = 0;
  let sumSquares = 0;
  for (let offset = 44; offset < left.length; offset += 3) {
    const delta = left.readIntLE(offset, 3) - right.readIntLE(offset, 3);
    maximum = Math.max(maximum, Math.abs(delta));
    if (delta) changed++;
    sumSquares += delta * delta;
  }
  const count = (left.length - 44) / 3;
  return { byteExact: left.equals(right), maximumAbsoluteDeltaPcm24Lsb: maximum,
    changedSamples: changed, comparedSamples: count,
    normalizedRmsError: Math.sqrt(sumSquares / count) / 8388608 };
}
try {
  sample();
  sampler = setInterval(sample, 200);
  const start = performance.now();
  await server.start();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  await page.route("**/*", (route) => new URL(route.request().url()).origin === server.origin ? route.continue() : route.abort());
  await page.goto(`${server.origin}/render`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => typeof window.motifForgeRender === "function");
  const startupMs = performance.now() - start;
  const fixture = buildThirtySecondSpikeGraph();
  const legacy = JSON.parse(await readFile(resolve(output, "legacy-audio-graph.v1.json"), "utf8"));
  const canonicalLegacy = JSON.parse(await readFile(resolve(output, "legacy-canonical-audio-graph.v1.json"), "utf8"));
  const cases = [["thirty-cold", fixture], ["thirty-warm", fixture], ["thirty-pluck-stem", fixture, ["pluck"]], ["legacy-seventy-two", legacy], ["legacy-canonical-reopened", canonicalLegacy]];
  try { cases.push(["historical-export-reopened", JSON.parse(await readFile(resolve(output, "historical-audio-graph.v1.json"), "utf8"))]); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  for (const [name, graph, scope] of cases) {
    phase = name;
    sample();
    const token = randomBytes(16).toString("hex");
    const target = resolve(output, `${name}.wav`);
    server.registerSink(token, target, 64 * 1024 * 1024);
    const began = performance.now();
    const receipt = await withTimeout(page.evaluate((request) => window.motifForgeRender(request), {
      requestVersion: "render-bridge-request.v1", requestId: name, outputToken: token,
      outputBitDepth: 24, graph, ...(scope ? { renderTrackIds: scope } : {}),
    }), 120000, () => page.close());
    const latencyMs = performance.now() - began;
    sample();
    const bytes = await readFile(target);
    const probe = JSON.parse(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration,size:stream=codec_name,sample_rate,channels,bits_per_raw_sample", "-of", "json", target], { encoding: "utf8" }));
    const expectedBytes = graph.durationSeconds * 48000 * 2 * 3 + 44;
    if (receipt.bytes !== bytes.length || bytes.length !== expectedBytes || Math.abs(receipt.durationSeconds - graph.durationSeconds) > 1 / 48000 || receipt.peak <= 0.001 || receipt.peak > 1) throw new Error(`P0_RENDER_ACCEPTANCE_FAILED:${name}`);
    runs.push({ name, latencyMs, renderRealtimeFactor: latencyMs / (graph.durationSeconds * 1000), bytes: bytes.length,
      sha256: createHash("sha256").update(bytes).digest("hex"), receipt, ffprobe: probe,
      sampledMaximumProcessTreeRssBytes: Math.max(0, ...memory.filter((m) => m.phase === name).map((m) => m.processTreeRssBytes)) });
  }
  const left = await readFile(resolve(output, "thirty-cold.wav"));
  const right = await readFile(resolve(output, "thirty-warm.wav"));
  const canonicalReopenComparison = comparePcm24(
    await readFile(resolve(output, "legacy-seventy-two.wav")),
    await readFile(resolve(output, "legacy-canonical-reopened.wav")),
  );
  const report = { schemaVersion: "p0-render-baseline.v1", date: new Date().toISOString(), sourceHead: execFileSync("git", ["rev-parse", "HEAD"], { cwd: repo, encoding: "utf8" }).trim(),
    canonicalWorkerIntegration: false, mode: "host-headless-shared-compiler-not-docker-not-UI", historicalExportIncluded: runs.some((r) => r.name === "historical-export-reopened"), nodeVersion: process.version, chromiumVersion: browser.version(), startupMs,
    browserReused: true, providerRequests: 0, providerTokens: 0,
    memoryMethod: "200ms ps aggregate RSS of this Node process and descendants; shared pages may be counted twice; sampled, not physical peak/P95", memorySamplingAvailable: memory.length > 0,
    sampledMaximumProcessTreeRssBytes: Math.max(0, ...memory.map((m) => m.processTreeRssBytes)),
    repeat: comparePcm24(left, right), canonicalReopenComparison,
    canonicalReopenByteExact: canonicalReopenComparison.byteExact, runs };
  await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
  await writeFile(resolve(output, "memory-samples.json"), JSON.stringify(memory) + "\n", { flag: "wx" });
  console.log(JSON.stringify(report, null, 2));
} finally {
  clearInterval(sampler);
  await browser?.close();
  await server.close();
}
