#!/usr/bin/env node
/** Persisted Graph evidence + readable workbench browser acceptance. */

import { execFileSync, spawn } from "node:child_process";
import { chromium } from "playwright";

const WEB_URL = "http://127.0.0.1:5173";
const API_URL = (process.env.MOTIF_FORGE_API_URL ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const ASSERTION = "I reviewed this exact composition plan and both candidate previews.";
const TIMEOUT = 480_000;

function invariant(condition, message) { if (!condition) throw new Error(message); }
function compose(args) { return execFileSync("docker", ["compose", "-p", "agentic-music-workbench", ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 30_000 }).trim(); }
async function ready(url) { try { return (await fetch(url)).ok; } catch { return false; } }

async function attest() {
  invariant(["http://127.0.0.1:8000", "http://127.0.0.1:8100"].includes(API_URL), "Graph UI smoke only accepts the reviewed local API");
  const services = compose(["ps", "--services", "--status", "running"]).split("\n");
  for (const service of ["api", "dispatcher", "resume-dispatcher", "media-worker", "render-worker", "postgres", "redis"]) invariant(services.includes(service), `required service is not running: ${service}`);
  compose(["exec", "-T", "resume-dispatcher", "sh", "-c", 'test -z "$DEEPSEEK_API_KEY"']);
  invariant(await ready(`${API_URL}/health/ready`), "API readiness attestation failed");
  invariant(!(await ready(WEB_URL)), "Web port 5173 is already occupied");
}

async function startWeb() {
  const child = spawn("npm", ["run", "dev:web", "--", "--host", "127.0.0.1", "--strictPort"], { detached: true, stdio: "ignore", env: { ...process.env, MOTIF_FORGE_API_PROXY_TARGET: API_URL } });
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) { if (await ready(WEB_URL)) return child; await new Promise((resolve) => setTimeout(resolve, 250)); }
  if (child.pid) process.kill(-child.pid, "SIGTERM");
  throw new Error("Web server did not become ready");
}

async function stopWeb(child) {
  if (!child?.pid) return;
  try { process.kill(-child.pid, "SIGTERM"); } catch { return; }
  const deadline = Date.now() + 5_000;
  while (Date.now() < deadline) {
    try { process.kill(child.pid, 0); } catch { return; }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Web process ${child.pid} did not exit after SIGTERM`);
}

async function data(response) { invariant(response.ok(), `public API failed: ${response.status()}`); const body = await response.json(); invariant(body?.data, "public API response is missing data"); return body.data; }
async function readRun(page, runId) { return page.evaluate(async (id) => { const response = await fetch(`/api/v1/runs/${encodeURIComponent(id)}`); if (!response.ok) throw new Error(`Run read failed: ${response.status}`); return (await response.json()).data; }, runId); }
async function waitRun(page, runId, predicate, label) { const deadline = Date.now() + TIMEOUT; while (Date.now() < deadline) { const run = await readRun(page, runId); if (predicate(run)) return run; await page.waitForTimeout(350); } throw new Error(`Run did not reach ${label}`); }
async function noPageOverflow(page, label) { invariant(!(await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1)), `${label} has document-level horizontal overflow`); }

async function journey(page) {
  const projectName = `Graph Evidence ${Date.now().toString(36)}`;
  await page.goto(WEB_URL, { waitUntil: "networkidle" });
  await page.getByLabel("搜索作品").waitFor();
  await page.getByLabel("作品状态").selectOption("all");
  await page.getByLabel("作品名称").fill(projectName);
  const projectResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/projects");
  await page.getByRole("button", { name: "创建作品" }).click();
  const project = await data(await projectResponse);
  const card = page.locator(".project-card").filter({ hasText: projectName });
  await card.getByRole("button", { name: "新建编曲" }).click();

  await page.getByLabel("作品标题").fill("Visible Parent Graph");
  await page.getByLabel("用途").fill("Instrumental background for a quiet orbital observatory");
  await page.getByLabel("情绪").fill("weightless, curious");
  await page.getByLabel("目标时长（秒）").fill("60");
  await page.getByText("高级编曲约束", { exact: true }).click();
  await page.getByLabel("目标 BPM").fill("72");
  await page.getByLabel("目标调性").fill("D dorian");
  const runResponse = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname.endsWith("/ai-runs"));
  await page.getByRole("button", { name: "提交 Brief 并规划" }).click();
  const run = await data(await runResponse);
  const runId = run.run_id;

  await waitRun(page, runId, (value) => value.pending_action === "approve_plan", "PlanApproval");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByLabel("Agent 执行路径").waitFor();
  await page.getByLabel("审批人").fill("portfolio-owner");
  await page.getByLabel("审批确认").fill(ASSERTION);
  await page.getByRole("button", { name: "批准并生成" }).click();
  await waitRun(page, runId, (value) => value.pending_action === "select_candidate", "CandidateSelection");
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByLabel("选择确认").fill(ASSERTION);
  await page.getByRole("button", { name: "选择候选 B" }).click();
  const terminal = await waitRun(page, runId, (value) => ["succeeded", "failed"].includes(value.status), "terminal export");
  invariant(terminal.status === "succeeded" && terminal.revision_id, `Generate failed: ${terminal.error_code ?? terminal.status}`);
  invariant(terminal.submitted_model_requests === 0, "No-key flow unexpectedly used a paid model request");

  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByLabel("Agent 执行路径").waitFor();
  await page.getByRole("link", { name: "查看完整 Graph" }).click();
  await page.getByLabel("Generate Parent Graph 执行路径").waitFor();
  await page.getByText("理解与规划", { exact: true }).first().waitFor();
  await page.getByText("ValidateRequest", { exact: true }).first().waitFor();
  await page.getByLabel("并行候选分支").waitFor();
  const exportLoop = page.locator(".graph-loop-group summary");
  if (await exportLoop.count()) await exportLoop.click();
  await page.getByRole("button", { name: /校验生成请求/ }).click();
  await page.getByRole("region", { name: "节点证据" }).getByText("ValidateRequest", { exact: true }).waitFor();

  await page.getByRole("link", { name: "打开 Studio" }).click();
  const arrangement = page.getByRole("main", { name: "Arrangement 主工作区" });
  const inspector = page.getByRole("complementary", { name: "Studio Inspector" });
  await arrangement.waitFor();
  invariant(await arrangement.evaluate((node, other) => Boolean(node.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING), await inspector.elementHandle()), "Studio Inspector precedes Arrangement in DOM order");
  await page.setViewportSize({ width: 390, height: 844 });
  await noPageOverflow(page, "Studio mobile");
  await page.goto(`${WEB_URL}/runs/${runId}/inspect`, { waitUntil: "domcontentloaded" });
  await page.getByLabel("Generate Parent Graph 执行路径").waitFor();
  await noPageOverflow(page, "Inspector mobile");

  console.log(JSON.stringify({ project_id: project.project_id, run_id: runId, revision_id: terminal.revision_id, graph_evidence: true, mobile_overflow: false, provider_requests: terminal.submitted_model_requests }));
}

async function main() {
  await attest();
  const web = await startWeb();
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage({ viewport: { width: 1365, height: 900 } });
    page.setDefaultTimeout(30_000);
    await journey(page);
  } finally {
    if (browser) await browser.close();
    await stopWeb(web);
  }
}

main().catch((error) => { console.error(`Graph UI browser smoke failed: ${error instanceof Error ? error.message : String(error)}`); process.exitCode = 1; });
