#!/usr/bin/env node
/** Presentation-only smoke: no Docker, no API server, no model requests. */
import assert from "node:assert/strict";
import { mkdir, copyFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import { chromium } from "playwright";
import { projectId, revisionId, runId, project, projects, run, studio, graph, inspection, exportData } from "./fixtures/product-ui.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = resolve(root, "output/playwright/light-studio");
const url = "http://127.0.0.1:5178";
const server = await createServer({ configFile: resolve(root, "apps/web/vite.config.ts"), server: { port: 5178, strictPort: true, host: "127.0.0.1" } });
let browser;
let mode = "approval";
let homeState = "normal";
let partialStudio = false;
const errors = [];
const unexpected = [];
// Silent PCM is a media-element fixture, not a music-generation result.
const silence = Buffer.alloc(44 + 8000 * 2 * 92);
silence.write("RIFF", 0); silence.writeUInt32LE(silence.length - 8, 4); silence.write("WAVEfmt ", 8);
silence.writeUInt32LE(16, 16); silence.writeUInt16LE(1, 20); silence.writeUInt16LE(1, 22);
silence.writeUInt32LE(8000, 24); silence.writeUInt32LE(16000, 28); silence.writeUInt16LE(2, 32); silence.writeUInt16LE(16, 34);
silence.write("data", 36); silence.writeUInt32LE(silence.length - 44, 40);

try {
  await mkdir(output, { recursive: true });
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce", locale: "zh-CN" });
  page.on("pageerror", (error) => errors.push(error.message));
  // An intentionally open SSE connection represents a stable approval wait.
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.fetch = (input, init) => {
      if (String(input).endsWith("/events")) return Promise.resolve(new Response(new ReadableStream({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(": connected\n\n"));
          init?.signal?.addEventListener("abort", () => controller.close(), { once: true });
        },
      }), { headers: { "Content-Type": "text/event-stream" } }));
      return original(input, init);
    };
  });
  await page.route("**/*", async (route) => {
    const request = route.request();
    const target = new URL(request.url());
    if (target.origin !== url) { unexpected.push(target.origin); return route.abort(); }
    const path = target.pathname;
    if (!path.startsWith("/api/")) return route.continue();
    const json = (data, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify({ data }) });
    if (path === "/api/v1/projects") {
      if (request.method() === "POST") return json({ project_id: projectId, active_branch_id: project.active_branch_id, root_revision_id: revisionId, content_hash: "demo", replayed: false }, 201);
      if (homeState === "loading") return new Promise(() => {});
      if (homeState === "error") return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { message: "演示：本地服务暂不可用，请确认服务已启动。", code: "SERVICE_UNAVAILABLE" } }) });
      return json(homeState === "empty" ? [] : homeState === "long" ? [{ ...projects[0], name: "这是一段很长的作品名称，用来确认窄屏下内容会自然换行，而不会把工作区撑出页面之外 / A composition with a long name" }] : projects);
    }
    if (path === "/api/v1/sound-catalog") return json([]);
    if (path.endsWith("/studio")) return json(partialStudio ? { ...studio, bundle_id: null, delivery_assets: [{ ...studio.delivery_assets[0], availability: "evicted" }] } : studio);
    if (path.endsWith("/exports")) return json(exportData);
    if (path.endsWith("/inspect")) return json(inspection);
    if (path.endsWith("/graph")) {
      const value = structuredClone(graph);
      if (!request.headers().referer?.includes("/inspect") && mode !== "done") {
        value.run_status = mode === "approval" ? "waiting_approval" : "waiting_worker";
        value.current_phase_id = mode === "approval" ? "approval" : "critique";
        const waitingIndex = mode === "approval" ? 1 : 3;
        value.phases.forEach((phase, index) => { phase.status = index < waitingIndex ? "completed" : index === waitingIndex ? "waiting" : "not_visited"; phase.summary = index < waitingIndex ? phase.summary : index === waitingIndex ? "等待你的确认" : "尚未执行"; });
        value.nodes.forEach((node) => { node.status = value.phases.find((phase) => phase.id === node.phase_id).status; });
      }
      return json(value);
    }
    if (path === `/api/v1/projects/${projectId}`) return json(project);
    if (path === `/api/v1/runs/${runId}`) return json(run(mode));
    if (path.endsWith("/content")) return route.fulfill({ status: 200, contentType: "audio/wav", body: silence });
    unexpected.push(`${request.method()} ${path}`);
    return route.fulfill({ status: 404, body: "Unmocked request" });
  });

  async function check(label, path, ready, screenshot = true) {
    await page.goto(`${url}${path}`, { waitUntil: "domcontentloaded" });
    await ready();
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.locator("main").count(), 1, `${label}: only one main landmark`);
    assert.equal(await page.getByRole("navigation", { name: "主导航" }).isVisible(), true, `${label}: navigation remains available`);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert(overflow <= 1, `${label}: page overflow ${overflow}px`);
    if (screenshot) {
      await page.evaluate(() => {
        document.querySelector("footer span").textContent = "界面演示 · 示例数据，非实测生成结果";
        window.scrollTo(0, 0);
      });
      await page.screenshot({ path: resolve(output, `${label}.png`), fullPage: true, animations: "disabled" });
    }
    console.log(`PASS ${label}`);
  }
  const paths = {
    home: ["/", () => page.getByLabel("作品列表").waitFor()],
    brief: [`/projects/${projectId}/new-composition`, () => page.getByLabel("作品标题").waitFor()],
    approval: [`/runs/${runId}`, () => page.getByRole("button", { name: "批准并生成" }).waitFor()],
    studio: [`/projects/${projectId}/studio/${revisionId}`, () => page.getByLabel("时间线画布").waitFor()],
    export: [`/projects/${projectId}/exports/${revisionId}`, () => page.getByRole("link", { name: "下载 Master WAV" }).waitFor()],
    graph: [`/runs/${runId}/inspect`, () => page.getByRole("button", { name: /校验生成请求/ }).waitFor()],
    import: [`/projects/${projectId}/import`, () => page.locator(".import-flow").waitFor()],
    about: ["/about", () => page.getByRole("heading", { name: /把音乐做完整/ }).waitFor()],
    evaluation: ["/evaluation", () => page.getByText("实测通过", { exact: true }).waitFor()],
  };
  for (const [name, [path, ready]] of Object.entries(paths)) await check(name, path, ready);
  mode = "candidates";
  await check("candidates", `/runs/${runId}`, () => page.getByRole("button", { name: "选择候选 B" }).waitFor());
  assert.equal(await page.getByRole("button", { name: "选择候选 B" }).isEnabled(), false, "selection still requires explicit confirmation");
  await page.getByLabel("选择确认").fill("我已比较两个候选的结构和试听，确认选择喜欢的音乐方向。");
  assert.equal(await page.getByRole("button", { name: "选择候选 B" }).isEnabled(), true);
  mode = "done";
  await check("completed", `/runs/${runId}`, () => page.getByRole("button", { name: "打开 Studio" }).waitFor());
  await check("studio-mixer", paths.studio[0], async () => { await paths.studio[1](); await page.getByRole("tab", { name: "混音台" }).click(); await page.locator(".mixer-panel").waitFor(); });
  await check("graph-evidence", paths.graph[0], async () => { await paths.graph[1](); await page.getByRole("button", { name: /校验生成请求/ }).click(); await page.getByRole("region", { name: "节点证据" }).getByText("ValidateRequest").waitFor(); });
  await page.locator(".run-graph-toolbar .path-kicker").evaluate((element) => { element.textContent += " · 界面演示 / 示例数据"; });
  await page.locator(".run-graph-view").screenshot({ path: resolve(output, "graph-detail.png"), animations: "disabled" });
  mode = "approval";
  await page.setViewportSize({ width: 390, height: 844 });
  for (const [name, [path, ready]] of Object.entries(paths)) {
    await check(`mobile-${name}`, path, ready);
    if (name === "studio") {
      assert.equal(await page.locator(".mobile-review-note").isVisible(), true);
      assert.equal(await page.locator(".studio-toolbar").isVisible(), false);
      assert.equal(await page.locator(".studio-dock").isVisible(), false);
    }
  }
  mode = "candidates";
  await check("mobile-candidates", `/runs/${runId}`, () => page.getByRole("button", { name: "选择候选 B" }).waitFor());
  homeState = "long"; await check("mobile-long-title", "/", paths.home[1]);
  homeState = "empty"; await check("empty", "/", () => page.getByText("还没有作品", { exact: true }).waitFor());
  homeState = "error"; await check("error", "/", () => page.getByRole("button", { name: "重试载入" }).waitFor());
  homeState = "loading"; await check("loading", "/", () => page.getByRole("status", { name: "正在载入项目" }).waitFor());
  homeState = "normal";
  partialStudio = true; await check("partial-studio", paths.studio[0], () => page.getByRole("button", { name: "恢复 MP3" }).waitFor());
  assert.deepEqual(errors, [], "no client runtime errors");
  assert.deepEqual(unexpected, [], "no unmocked API or external requests");
  if (process.argv.includes("--docs")) {
    const docs = resolve(root, "docs/images");
    await mkdir(docs, { recursive: true });
    for (const [from, to] of [["home", "workbench"], ["studio-mixer", "studio"], ["graph-detail", "graph"], ["candidates", "candidates"]]) await copyFile(resolve(output, `${from}.png`), resolve(docs, `${to}.png`));
  }
  console.log("UI smoke passed. All API data was isolated demo data; no backend or model was contacted.");
} finally {
  await browser?.close();
  await server.close();
  console.log("Browser and Vite stopped.");
}
