#!/usr/bin/env node
/** No-Key browser acceptance for Brief → Plan → A/B → selected Revision → Studio. */

import { execFileSync, spawn } from "node:child_process";
import { chromium } from "playwright";

const WEB_URL = (process.env.MOTIF_FORGE_WEB_URL ?? "http://127.0.0.1:5173").replace(/\/$/, "");
const API_URL = (process.env.MOTIF_FORGE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const ASSERTION = (process.env.MOTIF_FORGE_S5_APPROVAL_ASSERTION ?? "I reviewed the exact Plan and both candidate previews.").trim();
const ACTOR = (process.env.MOTIF_FORGE_S5_APPROVAL_ACTOR ?? "portfolio-owner").trim();
const TIMEOUT = 480_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function invariant(condition, message) { if (!condition) throw new Error(message); }
function docker(args) {
  return execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 30_000 }).trim();
}

async function attestBeforeMutation() {
  const apiOrigin = new URL(API_URL);
  invariant(
    WEB_URL === "http://127.0.0.1:5173"
      && apiOrigin.protocol === "http:"
      && apiOrigin.hostname === "127.0.0.1"
      && ["8000", "8100"].includes(apiOrigin.port),
    "S5 smoke requires reviewed local origins",
  );
  const services = docker(["compose", "ps", "--services", "--status", "running"]).split("\n");
  for (const service of ["api", "dispatcher", "resume-dispatcher", "media-worker", "render-worker", "postgres", "redis"]) {
    invariant(services.includes(service), `required Compose service is not running: ${service}`);
  }
  docker(["compose", "exec", "-T", "resume-dispatcher", "sh", "-c", 'test -z "$DEEPSEEK_API_KEY"']);
  const ready = await fetch(`${API_URL}/health/ready`);
  invariant(ready.ok, "API readiness attestation failed");
}

async function webReady() { try { return (await fetch(WEB_URL)).ok; } catch { return false; } }
async function startWeb() {
  if (await webReady()) throw new Error("S5 Web port is occupied; refusing an unattested server");
  const child = spawn("npm", ["run", "dev:web", "--", "--host", "127.0.0.1", "--strictPort"], {
    detached: true,
    stdio: "ignore",
    env: { ...process.env, MOTIF_FORGE_API_PROXY_TARGET: API_URL },
  });
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await webReady()) return child;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (child.pid) process.kill(-child.pid, "SIGTERM");
  throw new Error("S5 Web server did not become ready");
}
function stopWeb(child) { if (child?.pid) try { process.kill(-child.pid, "SIGTERM"); } catch { /* stopped */ } }

async function responseData(response) {
  invariant(response.ok(), `public API failed: ${response.status()}`);
  const body = await response.json();
  invariant(body?.data, "public API response is missing data");
  return body.data;
}
async function readRun(page, runId) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/runs/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`Run read failed: ${response.status}`);
    return (await response.json()).data;
  }, runId);
}
async function waitFor(page, runId, predicate, label) {
  const deadline = Date.now() + TIMEOUT;
  while (Date.now() < deadline) {
    const run = await readRun(page, runId);
    if (predicate(run)) return run;
    await page.waitForTimeout(300);
  }
  throw new Error(`S5 Run did not reach ${label}`);
}
async function noOverflow(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  invariant(!overflow, `${label} has horizontal overflow at 390 px`);
}

function sqlFacts(projectId, runId, revisionId) {
  for (const value of [projectId, runId, revisionId]) invariant(UUID.test(value), "invalid SQL evidence identifier");
  const sql = `SELECT json_build_object(
    'candidate_families',(SELECT count(DISTINCT candidate_id) FROM app.candidate_snapshots WHERE source_run_id='${runId}'),
    'candidate_snapshots',(SELECT count(*) FROM app.candidate_snapshots WHERE source_run_id='${runId}'),
    'repair_children',(SELECT count(*) FROM app.candidate_snapshots WHERE source_run_id='${runId}' AND parent_candidate_snapshot_id IS NOT NULL),
    'selection_previews',(SELECT count(*) FROM app.preview_candidates WHERE source_run_id='${runId}'),
    'selected_revisions',(SELECT count(*) FROM app.project_revisions WHERE source_run_id='${runId}' AND id='${revisionId}'),
    'receipts',(SELECT count(*) FROM app.composition_materialization_receipts WHERE run_id='${runId}' AND revision_id='${revisionId}'),
    'export_jobs',(SELECT count(*) FROM app.jobs j JOIN app.runs r ON r.id=j.run_id WHERE j.project_id='${projectId}' AND r.run_type='complete_song_export.v1'),
    'audio_artifacts',(SELECT count(*) FROM app.artifacts WHERE revision_id='${revisionId}'),
    'bundles',(SELECT count(*) FROM app.export_bundle_artifacts WHERE revision_id='${revisionId}'),
    'provider_reservations',(SELECT count(*) FROM app.ai_model_request_reservations WHERE run_id='${runId}')
  )::text;`;
  return JSON.parse(docker(["compose", "exec", "-T", "postgres", "psql", "-U", "motif_forge", "-d", "motif_forge", "-Atc", sql]));
}

async function journey(page) {
  const name = `S5 Portfolio ${Date.now().toString(36)}`;
  await page.goto(WEB_URL, { waitUntil: "networkidle" });
  await page.getByLabel("作品名称").fill(name);
  const projectResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/projects");
  await page.getByRole("button", { name: "创建作品" }).click();
  const project = await responseData(await projectResponse);
  await page.locator(".project-card").filter({ hasText: name }).getByRole("button", { name: "新建编曲" }).click();
  await page.getByLabel("作品标题").fill("S5 Candidate Orbit");
  await page.getByLabel("用途").fill("Instrumental background for a quiet orbital observatory");
  await page.getByLabel("情绪").fill("weightless, curious");
  await page.getByLabel("目标时长（秒）").fill("60");
  await page.getByLabel("目标 BPM").fill("72");
  await page.getByLabel("目标调性").fill("D dorian");
  const runResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/ai-runs"));
  await page.getByRole("button", { name: "提交 Brief 并规划" }).click();
  const run = await responseData(await runResponse);
  const runId = run.run_id;
  invariant(UUID.test(runId), "S5 Run ID is invalid");
  await waitFor(page, runId, (value) => value.pending_action === "approve_plan", "PlanApproval");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByLabel("审批人").fill(ACTOR);
  await page.getByLabel("审批确认").fill(ASSERTION);
  await page.getByRole("button", { name: "批准并生成" }).click();

  await waitFor(page, runId, (value) => value.pending_action === "select_candidate", "CandidateSelection");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "比较候选 A / B" }).waitFor();
  await page.getByRole("button", { name: "试听候选 A" }).click();
  invariant(await page.getByLabel("候选 A 试听").count() === 1, "Candidate A Preview did not mount");
  await page.getByRole("button", { name: "试听候选 B" }).click();
  invariant(await page.getByLabel("候选 B 试听").count() === 1 && await page.locator(".candidate-card audio").count() === 1, "candidate playback is not exclusive");
  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page, "Candidate compare");
  await page.getByLabel("选择确认").fill(ASSERTION);
  await page.getByRole("button", { name: "选择候选 B" }).click();
  const terminal = await waitFor(page, runId, (value) => ["succeeded", "failed"].includes(value.status), "terminal export");
  invariant(terminal.status === "succeeded" && UUID.test(terminal.revision_id), `S5 failed: ${terminal.error_code ?? terminal.status}`);
  invariant(terminal.submitted_model_requests === 0 && terminal.total_tokens === 0, "S5 browser smoke recorded model usage");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("button", { name: "打开只读 Studio" }).click();
  await page.getByRole("heading", { name: "作品试听" }).waitFor();
  invariant((await page.locator("audio").getAttribute("src"))?.includes("/audio-artifacts/"), "Studio has no authoritative audio");
  await noOverflow(page, "Selected Studio");
  const facts = sqlFacts(project.project_id, runId, terminal.revision_id);
  invariant(facts.candidate_families === 2 && [2, 3].includes(facts.candidate_snapshots), "candidate Snapshot counts are invalid");
  invariant([0, 1].includes(facts.repair_children) && facts.selection_previews === 2, "Repair/Preview bounds are invalid");
  invariant(facts.selected_revisions === 1 && facts.receipts === 1, "selected Revision is not unique");
  invariant(facts.export_jobs === 7 && facts.audio_artifacts === 6 && facts.bundles === 1, "complete export counts are invalid");
  invariant(facts.provider_reservations === 0, "no-Key journey reserved a provider request");
  const summary = { project_id: project.project_id, run_id: runId, revision_id: terminal.revision_id, ...facts, provider_requests: terminal.submitted_model_requests, provider_tokens: terminal.total_tokens, mobile_overflow: false };
  invariant(JSON.stringify(summary).length < 4096, "S5 browser summary is not bounded");
  console.log(JSON.stringify(summary));
}

async function main() {
  invariant(ACTOR.length > 0 && ASSERTION.length >= 16, "S5 actor/assertion is invalid");
  await attestBeforeMutation();
  const web = await startWeb();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
    page.setDefaultTimeout(30_000);
    await journey(page);
  } finally {
    await browser.close();
    stopWeb(web);
  }
}

main().catch((error) => { console.error(`S5 browser smoke failed: ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; });
