#!/usr/bin/env node
/** Deterministic browser acceptance for the complete S3 composition journey. */

import { execFileSync, spawn } from "node:child_process";
import { chromium } from "playwright";

const WEB_URL = (process.env.MOTIF_FORGE_WEB_URL ?? "http://127.0.0.1:5173").replace(/\/$/, "");
const API_URL = (process.env.MOTIF_FORGE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const ACTOR = (process.env.MOTIF_FORGE_S3_APPROVAL_ACTOR ?? "portfolio-owner").trim();
const ASSERTION = (process.env.MOTIF_FORGE_S3_APPROVAL_ASSERTION ?? "I approve this deterministic portfolio plan").trim();
const JOURNEY_TIMEOUT = 480_000;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

function quietDocker(args) {
  return execFileSync("docker", args, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 20_000 }).trim();
}

async function assertNoPaidRuntime() {
  const services = quietDocker(["compose", "ps", "--services", "--status", "running"]).split("\n");
  for (const required of ["api", "dispatcher", "resume-dispatcher", "media-worker", "render-worker", "postgres", "redis"]) {
    invariant(services.includes(required), `required Compose service is not running: ${required}`);
  }
  quietDocker(["compose", "exec", "-T", "resume-dispatcher", "sh", "-c", 'test -z "$DEEPSEEK_API_KEY"']);
  const response = await fetch(`${API_URL}/health/ready`);
  invariant(response.ok, "API readiness attestation failed");
}

function assertLocalRuntimeTargets() {
  invariant(WEB_URL === "http://127.0.0.1:5173", "S3 deterministic smoke requires the reviewed local Web origin");
  invariant(API_URL === "http://127.0.0.1:8000", "S3 deterministic smoke requires the attested local API origin");
}

async function webIsReady() {
  try {
    const response = await fetch(WEB_URL);
    return response.ok;
  } catch {
    return false;
  }
}

async function startWebIfNeeded() {
  if (await webIsReady()) throw new Error("S3 Web port is already occupied; refusing to reuse an unattested server");
  const child = spawn("npm", ["run", "dev:web", "--", "--host", "127.0.0.1", "--strictPort"], {
    detached: true,
    stdio: "ignore",
  });
  let exitCode;
  child.once("exit", (code) => { exitCode = code ?? 1; });
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (exitCode !== undefined) throw new Error(`S3 Web server exited before readiness: ${exitCode}`);
    if (await webIsReady()) return child;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (child.pid) process.kill(-child.pid, "SIGTERM");
  throw new Error("S3 web server did not become ready");
}

function stopWeb(child) {
  if (child?.pid) {
    try { process.kill(-child.pid, "SIGTERM"); } catch { /* already stopped */ }
  }
}

async function responseData(response) {
  invariant(response.ok(), `public API failed: ${response.request().method()} ${new URL(response.url()).pathname} ${response.status()}`);
  const body = await response.json();
  invariant(body && typeof body === "object" && body.data, "public API response is missing data");
  return body.data;
}

async function publicRun(page, runId) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/runs/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`Run read failed: ${response.status}`);
    return (await response.json()).data;
  }, runId);
}

async function publicProject(page, projectId) {
  return page.evaluate(async (id) => {
    const response = await fetch(`/api/v1/projects/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error(`Project read failed: ${response.status}`);
    return (await response.json()).data;
  }, projectId);
}

async function waitForRunStatus(page, runId, statuses, timeout = 60_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const run = await publicRun(page, runId);
    if (statuses.includes(run.status)) return run;
    await page.waitForTimeout(250);
  }
  throw new Error(`Run did not reach ${statuses.join("/")}`);
}

async function waitForPlan(page) {
  await page.locator(".plan-review").waitFor({ state: "visible", timeout: 60_000 });
  return page.locator(".plan-review").innerText();
}

async function assertNoPageOverflow(page, label) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  invariant(!overflow, `${label} has page-level horizontal overflow at 390 px`);
  return overflow;
}

function wavFixture(frequency) {
  const sampleRate = 16_000;
  const seconds = 3;
  const samples = sampleRate * seconds;
  const dataBytes = samples * 2;
  const buffer = Buffer.alloc(44 + dataBytes);
  buffer.write("RIFF", 0); buffer.writeUInt32LE(36 + dataBytes, 4); buffer.write("WAVE", 8);
  buffer.write("fmt ", 12); buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22); buffer.writeUInt32LE(sampleRate, 24); buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34); buffer.write("data", 36); buffer.writeUInt32LE(dataBytes, 40);
  for (let index = 0; index < samples; index += 1) {
    const beat = index % Math.floor(sampleRate / 2);
    const envelope = beat < sampleRate * 0.08 ? 1 - beat / (sampleRate * 0.08) : 0;
    const value = Math.round(Math.sin(2 * Math.PI * frequency * index / sampleRate) * envelope * 12_000);
    buffer.writeInt16LE(value, 44 + index * 2);
  }
  return buffer;
}

function sqlFacts(projectId, parentRunId, childRunId, revisionId) {
  for (const value of [projectId, parentRunId, childRunId, revisionId]) invariant(UUID.test(value), "invalid identifier before SQL evidence query");
  const sql = `
    SELECT json_build_object(
      'parent_plan_count', (SELECT count(*) FROM app.composition_plans WHERE run_id='${parentRunId}'),
      'child_plan_count', (SELECT count(*) FROM app.composition_plans WHERE run_id='${childRunId}'),
      'revision_count', (SELECT count(*) FROM app.project_revisions WHERE id='${revisionId}' AND source_run_id='${childRunId}'),
      'receipt_count', (SELECT count(*) FROM app.composition_materialization_receipts WHERE run_id='${childRunId}' AND revision_id='${revisionId}'),
      'job_count', (SELECT count(*) FROM app.jobs WHERE project_id='${projectId}'),
      'audio_artifact_count', (SELECT count(*) FROM app.artifacts WHERE revision_id='${revisionId}'),
      'bundle_count', (SELECT count(*) FROM app.export_bundle_artifacts WHERE revision_id='${revisionId}'),
      'media_run_count', (SELECT count(DISTINCT run_id) FROM app.jobs WHERE project_id='${projectId}'),
      'media_run_id', (SELECT run_id FROM app.jobs WHERE project_id='${projectId}' ORDER BY created_at LIMIT 1),
      'media_run_type', (SELECT run_type FROM app.runs WHERE id=(SELECT run_id FROM app.jobs WHERE project_id='${projectId}' ORDER BY created_at LIMIT 1)),
      'succeeded_job_count', (SELECT count(*) FROM app.jobs WHERE project_id='${projectId}' AND status='succeeded'),
      'source_lineage_count', (
        SELECT count(*) FROM (
          SELECT source_job_id FROM app.artifacts WHERE revision_id='${revisionId}'
          UNION ALL
          SELECT source_job_id FROM app.export_bundle_artifacts WHERE revision_id='${revisionId}'
        ) outputs WHERE source_job_id IN (SELECT id FROM app.jobs WHERE project_id='${projectId}')
      ),
      'source_lineage_distinct_count', (
        SELECT count(DISTINCT source_job_id) FROM (
          SELECT source_job_id FROM app.artifacts WHERE revision_id='${revisionId}'
          UNION ALL
          SELECT source_job_id FROM app.export_bundle_artifacts WHERE revision_id='${revisionId}'
        ) outputs
      ),
      'reservation_count', (SELECT count(*) FROM app.ai_model_request_reservations WHERE run_id IN ('${parentRunId}','${childRunId}'))
    )::text;`;
  const raw = quietDocker(["compose", "exec", "-T", "postgres", "psql", "-U", "motif_forge", "-d", "motif_forge", "-Atc", sql]);
  return JSON.parse(raw);
}

function sqlImportFacts(projectId) {
  invariant(UUID.test(projectId), "invalid Project identifier before Import evidence query");
  const sql = `
    SELECT json_build_object(
      'import_revision_count', (SELECT count(*) FROM app.project_revisions WHERE project_id='${projectId}' AND reason_code='AUDIO_IMPORT_MATERIALIZED'),
      'import_job_count', (SELECT count(*) FROM app.jobs WHERE project_id='${projectId}' AND job_type='ingest'),
      'import_run_count', (SELECT count(DISTINCT run_id) FROM app.jobs WHERE project_id='${projectId}' AND job_type='ingest')
    )::text;`;
  const raw = quietDocker(["compose", "exec", "-T", "postgres", "psql", "-U", "motif_forge", "-d", "motif_forge", "-Atc", sql]);
  return JSON.parse(raw);
}

async function completeImports(page, projectId, projectName) {
  await page.setViewportSize({ width: 1365, height: 900 });
  await page.locator(".brand-button").click();
  const card = page.locator(".project-card").filter({ hasText: projectName });
  await card.getByRole("button", { name: "导入音频" }).click();
  const head_before_imports = (await publicProject(page, projectId)).head_revision_id;
  const observedHeads = [];
  const collectHead = async (response) => {
    if (response.request().method() !== "GET" || new URL(response.url()).pathname !== `/api/v1/projects/${projectId}` || !response.ok()) return;
    const body = await response.json();
    if (body?.data?.head_revision_id) observedHeads.push(body.data.head_revision_id);
  };
  page.on("response", collectHead);
  await page.getByLabel("选择多个 Stem").setInputFiles([
    { name: "s3-pad.wav", mimeType: "audio/wav", buffer: wavFixture(220) },
    { name: "s3-pulse.wav", mimeType: "audio/wav", buffer: wavFixture(330) },
  ]);
  await page.getByLabel("确认 s3-pad.wav 的权利").check();
  await page.getByLabel("确认 s3-pulse.wav 的权利").check();
  await page.getByRole("button", { name: "开始顺序导入" }).click();
  const deadline = Date.now() + JOURNEY_TIMEOUT;
  while (Date.now() < deadline) {
    if (await page.getByText("2/2 Stem 已导入", { exact: true }).isVisible().catch(() => false)) break;
    const skipAlignment = page.getByRole("button", { name: "不对齐，直接导入" });
    if (await skipAlignment.isVisible().catch(() => false)) await skipAlignment.click();
    const alert = page.locator('[role="alert"]');
    if (await alert.isVisible().catch(() => false)) {
      const message = await alert.innerText();
      if (!message.includes("需要你的确认")) throw new Error(`Stem import failed: ${message}`);
    }
    await page.waitForTimeout(500);
  }
  invariant(await page.getByText("2/2 Stem 已导入", { exact: true }).isVisible().catch(() => false), "two-Stem queue did not complete");
  await page.waitForTimeout(500);
  page.off("response", collectHead);
  const head_after_second_import = (await publicProject(page, projectId)).head_revision_id;
  const distinct = [...new Set(observedHeads.filter((value) => value !== head_before_imports))];
  invariant(distinct.length === 2, "Project head must advance exactly once for each of two Stems");
  const head_after_first_import = distinct.find((value) => value !== head_after_second_import);
  invariant(head_after_first_import && head_after_first_import !== head_before_imports, "first Stem head is missing");
  invariant(head_after_second_import !== head_after_first_import, "second Stem did not create a new head");
  const importFacts = sqlImportFacts(projectId);
  invariant(importFacts.import_revision_count === 2, "two Stems must create exactly two Import Revisions");
  invariant(importFacts.import_job_count === 2 && importFacts.import_run_count === 2, "two Stems must use exactly two distinct Import Runs");
  return { head_before_imports, head_after_first_import, head_after_second_import, ...importFacts };
}

async function runJourney(page) {
  const suffix = Date.now().toString(36);
  const projectName = `S3 Portfolio ${suffix}`;
  await page.goto(WEB_URL, { waitUntil: "networkidle" });
  await page.getByLabel("作品名称").fill(projectName);
  const projectResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/projects");
  await page.getByRole("button", { name: "创建作品" }).click();
  const project = await responseData(await projectResponse);
  const projectId = project.project_id;
  invariant(UUID.test(projectId), "Project response has no valid ID");
  const projectCard = page.locator(".project-card").filter({ hasText: projectName });
  await projectCard.getByRole("button", { name: "新建编曲" }).click();

  await page.getByLabel("作品标题").fill("S3 Deterministic Orbit");
  await page.getByLabel("用途").fill("Instrumental background for a quiet orbital observatory");
  await page.getByLabel("情绪").fill("weightless, curious");
  await page.getByLabel("偏好乐器").fill("warm pad, soft pulse");
  await page.getByLabel("目标时长（秒）").fill("72");
  await page.getByLabel("目标 BPM").fill("72");
  await page.getByLabel("目标调性").fill("D dorian");
  await page.getByLabel("硬约束").fill("avoid clipping");
  await page.getByLabel("禁止项").fill("no abrupt drop");
  const runResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/ai-runs"));
  await page.getByRole("button", { name: "提交 Brief 并规划" }).click();
  const parent = await responseData(await runResponse);
  const parentRunId = parent.run_id;
  invariant(UUID.test(parentRunId), "parent Run response has no valid ID");
  await waitForRunStatus(page, parentRunId, ["waiting_approval"]);
  await page.reload({ waitUntil: "domcontentloaded" });
  const parentPlanText = await waitForPlan(page);
  invariant(page.url().endsWith(`/runs/${parentRunId}`), "waiting-approval refresh did not preserve the Run");
  await page.getByLabel("调整后的 BPM").fill("76");
  await page.getByLabel("调整说明").fill("Keep the same structure with a slightly clearer pulse.");
  const replanResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/replan"));
  await page.getByRole("button", { name: "创建调整后的 Plan" }).click();
  const child = await responseData(await replanResponse);
  const child_run_id = child.run_id;
  invariant(UUID.test(child_run_id) && child_run_id !== parentRunId, "replan did not create a distinct child Run");
  await waitForRunStatus(page, child_run_id, ["waiting_approval"]);
  await page.reload({ waitUntil: "domcontentloaded" });
  const childPlanText = await waitForPlan(page);
  invariant(childPlanText !== parentPlanText, "child Replan did not change the visible Plan");

  await page.goto(`${WEB_URL}/runs/${parentRunId}`, { waitUntil: "domcontentloaded" });
  const oldPlanAfterReplan = await waitForPlan(page);
  const old_plan_readable = oldPlanAfterReplan === parentPlanText;
  invariant(old_plan_readable, "parent Plan is no longer readable after replan");
  await page.goto(`${WEB_URL}/runs/${child_run_id}`, { waitUntil: "domcontentloaded" });
  invariant((await waitForPlan(page)) === childPlanText, "child Plan changed after navigation");
  await page.getByLabel("审批人").fill(ACTOR);
  await page.getByLabel("审批确认").fill(ASSERTION);
  await page.getByLabel("审批备注（可选）").fill("S3 deterministic browser approval");
  await page.getByRole("button", { name: "批准并生成" }).click();
  await page.getByRole("heading", { name: "作品已生成并写入 Revision" }).waitFor({ timeout: JOURNEY_TIMEOUT });
  const terminal = await publicRun(page, child_run_id);
  invariant(terminal.status === "succeeded" && UUID.test(terminal.revision_id), `approved Run did not succeed: ${terminal.error_code ?? terminal.status}`);
  invariant(terminal.submitted_model_requests === 0 && terminal.total_tokens === 0, "deterministic Run recorded model usage");
  const revisionId = terminal.revision_id;
  const facts = sqlFacts(projectId, parentRunId, child_run_id, revisionId);
  invariant(facts.parent_plan_count === 1 && facts.child_plan_count === 1, "immutable Plan counts are incorrect");
  invariant(facts.revision_count === 1 && facts.receipt_count === 1, "approved materialization facts are incorrect");
  invariant(facts.job_count === 7 && facts.succeeded_job_count === 7, "complete export must have seven succeeded Jobs");
  invariant(facts.audio_artifact_count === 6 && facts.bundle_count === 1, "complete export Artifact counts are incorrect");
  invariant(facts.media_run_count === 1 && facts.media_run_type === "complete_song_export.v1", "export Jobs do not belong to one complete-song Media Run");
  invariant(facts.source_lineage_count === 7 && facts.source_lineage_distinct_count === 7, "export outputs are not bound one-to-one to the seven Jobs");
  invariant(facts.reservation_count === 0, "deterministic Runs contain a provider reservation");

  await page.getByRole("button", { name: "打开只读 Studio" }).click();
  await page.getByRole("heading", { name: "作品试听" }).waitFor();
  await page.getByRole("heading", { name: "只读时间线" }).waitFor();
  const track_count = await page.getByLabel("轨道列表").locator(".track-header").count();
  invariant(track_count === 4, "Studio does not expose the four authoritative Arrangement tracks");
  const audioSource = await page.locator("audio").getAttribute("src");
  const audioPath = audioSource ? new URL(audioSource, WEB_URL).pathname : "";
  invariant(/^\/api\/v1\/audio-artifacts\/[0-9a-f-]+\/content$/i.test(audioPath), "Studio does not use the validated Artifact route");
  const deliveryBytes = await page.evaluate(async (source) => {
    const response = await fetch(source);
    if (!response.ok) throw new Error(`delivery MP3 fetch failed: ${response.status}`);
    return (await response.arrayBuffer()).byteLength;
  }, audioSource);
  invariant(deliveryBytes > 0, "delivery MP3 is physically empty");
  await page.getByRole("button", { name: "播放" }).click();
  await page.getByRole("button", { name: "暂停" }).waitFor({ timeout: 10_000 });
  const playback_started = await page.locator("audio").evaluate((audio) => !audio.paused);
  invariant(playback_started, "delivery MP3 playback did not start");
  await page.getByRole("button", { name: "暂停" }).click();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "作品试听" }).waitFor();
  const studioOverflow = await assertNoPageOverflow(page, "Studio");
  await page.goto(`${WEB_URL}/runs/${child_run_id}`, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "作品已生成并写入 Revision" }).waitFor();
  const runOverflow = await assertNoPageOverflow(page, "Run recovery");
  await page.locator(".brand-button").click();
  const reopenedCard = page.locator(".project-card").filter({ hasText: projectName });
  await reopenedCard.getByRole("button", { name: `打开 ${projectName} 最新版本` }).click();
  await page.getByRole("heading", { name: "作品试听" }).waitFor();
  const reopenOverflow = await assertNoPageOverflow(page, "Project reopen");

  const heads = await completeImports(page, projectId, projectName);
  const summary = {
    project_id: projectId,
    parent_run_id: parentRunId,
    child_run_id,
    approved_run_id: child_run_id,
    status: terminal.status,
    revision_id: revisionId,
    old_plan_readable,
    plan_count: facts.parent_plan_count + facts.child_plan_count,
    job_count: facts.job_count,
    audio_artifact_count: facts.audio_artifact_count,
    bundle_count: facts.bundle_count,
    media_run_id: facts.media_run_id,
    track_count,
    delivery_mp3_bytes: deliveryBytes,
    playback_started,
    provider_requests: terminal.submitted_model_requests,
    provider_tokens: terminal.total_tokens,
    mobile_overflow: studioOverflow || runOverflow || reopenOverflow,
    ...heads,
  };
  invariant(JSON.stringify(summary).length < 4096, "S3 summary is not bounded");
  console.log(JSON.stringify(summary));
}

async function main() {
  invariant(ACTOR.length > 0 && ASSERTION.length >= 16, "S3 approval actor/assertion is invalid");
  assertLocalRuntimeTargets();
  await assertNoPaidRuntime();
  const webProcess = await startWebIfNeeded();
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
    page.setDefaultTimeout(30_000);
    await runJourney(page);
  } finally {
    await browser.close();
    stopWeb(webProcess);
  }
}

main().catch((error) => {
  console.error(`S3 deterministic browser smoke failed: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
});
