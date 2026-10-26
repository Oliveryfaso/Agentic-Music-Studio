#!/usr/bin/env node
/** Real-browser UI verification with isolated, synthetic API responses only. */
import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import react from "@vitejs/plugin-react";
import { createServer } from "vite";
import { chromium } from "playwright";
import { projectId, revisionId, project, studio } from "./fixtures/product-ui.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const output = resolve(root, "output/playwright/settings");
await mkdir(output, { recursive: true });
await build({ entryPoints: [resolve(root, "apps/web/src/features/studio/pianoEqTestFixture.ts")], bundle: true, platform: "node", format: "esm", outfile: resolve(output, "piano-fixture.mjs") });
const { eqBase } = await import(pathToFileURL(resolve(output, "piano-fixture.mjs")).href);
const arrangement = eqBase();
arrangement.project_id = projectId;
arrangement.tempo_map = [{ tick: 0, bpm: 90 }];
arrangement.time_signature_map = [{ tick: 0, numerator: 4, denominator: 4 }];
arrangement.sections[0].end_tick = 15360;
arrangement.sections[0].label = "合成示例";
arrangement.tracks[0].name = "示例旋律";
arrangement.tracks[1].name = "示例伴奏";
arrangement.provenance = [{ kind: "asset", ref: "score:c02-la-candeur-a8.v1" }];
arrangement.tracks.forEach(track => track.clips.forEach((clip, index) => {
  clip.clip_id = `${track.track_id}-clip-${index}`;
  clip.notes?.forEach((note, n) => { note.note_id = `${track.track_id}-note-${index}-${n}`; });
}));
const workspace = { ...project, name: "设置入口 · 合成示例", recoverable_piano_preview: null, piano_preview_recovery: { status: "ready", pending_count: 0 } };
const saved = { ...studio, source_run_id: null, bundle_id: null, arrangement_ir: arrangement, delivery_assets: [] };
const classicalSource = { revision_id: revisionId, source: { score_id: "c02-la-candeur-a8.v1", title: "合成源谱示例", license: "CC0-1.0", conversion: "UI fixture only", page_url: "https://example.invalid/motif-ui-fixture", default_chords: Array(8).fill("C") }, import_report: { measure_count: 8, beats: 4, tonic: "C", note_count: 4 } };
const server = await createServer({ configFile: false, root: resolve(root, "apps/web"), cacheDir: resolve(output, ".vite"), plugins: [react()], server: { host: "127.0.0.1", port: 0, strictPort: true, hmr: false } });
let browser;
let configured = false;
let readFailure = false;
let checkMode = "connected";
let gate;
let checkCount = 0;
const requests = [], errors = [], unexpected = [], cases = [], captureGeometry = [];
const fromCase = process.argv.find(arg => arg.startsWith("--from="))?.slice(7);
let selected = !fromCase;
let page;
let origin;
const status = (text) => page.locator(".model-settings-status").getByText(text, { exact: true }).waitFor();
async function headingClear() {
  const box = await page.evaluate(() => ({ heading: document.querySelector("h1").getBoundingClientRect().top, topbar: document.querySelector(".topbar").getBoundingClientRect().bottom, scroll_y: scrollY }));
  assert(box.heading >= box.topbar - 1, `route heading hidden by sticky header: ${JSON.stringify(box)}`);
}
const checks = () => checkCount;
function defer() { let release; const promise = new Promise(resolve => { release = resolve; }); return { promise, release }; }

async function screenshot(name) {
  captureGeometry.push({ name, before_scroll_reset: await page.evaluate(() => {
    const h = document.querySelector("h1")?.getBoundingClientRect();
    const topbar = document.querySelector(".topbar")?.getBoundingClientRect();
    return { scroll_y: scrollY, heading_top: h?.top, heading_bottom: h?.bottom, topbar_bottom: topbar?.bottom };
  }) });
  await page.evaluate(() => {
    const badge = document.querySelector(".runtime-badge");
    if (badge) badge.textContent = "隔离 mock · 合成数据";
    window.scrollTo(0, 0);
  });
  await page.screenshot({ path: resolve(output, `${name}.png`), fullPage: true, animations: "disabled" });
}
async function geometry(locator) {
  return locator.evaluate(element => {
    const r = element.getBoundingClientRect();
    const center = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
    return { x: r.x, y: r.y, width: r.width, height: r.height, viewport: innerWidth, hit: center === element || element.contains(center) };
  });
}
async function run(name, fn) {
  if (!selected && name !== fromCase) return;
  selected = true;
  const before = checks();
  try { const details = await fn(); cases.push({ name, status: "passed", check_posts_before: before, check_posts_after: checks(), ...details }); console.log(`PASS ${name}`); }
  catch (error) { cases.push({ name, status: "failed", message: error.message }); await screenshot(`FAILED-${name}`).catch(() => {}); throw error; }
}
async function settings(value) { configured = value; readFailure = false; await page.goto(`${origin}/settings`, { waitUntil: "domcontentloaded" }); await status(value ? "已配置 · 未测试" : "未配置"); await headingClear(); }
async function idle() { await page.waitForLoadState("networkidle"); }

try {
  await server.listen();
  const address = server.httpServer.address();
  assert(address && typeof address !== "string");
  origin = `http://127.0.0.1:${address.port}`;
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: "zh-CN", reducedMotion: "reduce", serviceWorkers: "block" });
  page = await context.newPage();
  page.setDefaultTimeout(10000);
  page.on("pageerror", error => errors.push(error.message));
  page.on("request", request => requests.push({ method: request.method(), url: request.url() }));
  await context.route("**/*", async route => {
    const request = route.request(), target = new URL(request.url()), path = target.pathname;
    const json = (data, code = 200) => route.fulfill({ status: code, contentType: "application/json", body: JSON.stringify({ data }) });
    if (target.origin !== origin || path.startsWith("/health")) { unexpected.push(`${request.method()} ${target.origin}${path}`); return route.abort(); }
    if (request.method() === "POST" && path === "/api/v1/model-settings/check") {
      checkCount++;
      assert.equal(request.headers()["x-motif-configuration-check"], "1");
      assert.equal(request.postData(), null, "UI must not send a Key or music payload");
      if (checkMode === "gate") await gate.promise;
      if (checkMode === "network-error") return route.abort("timedout");
      if (checkMode === "auth") return json({ state: "failed", error_code: "AUTHENTICATION_FAILED" });
      if (checkMode === "timeout") return json({ state: "failed", error_code: "CONNECTION_FAILED" });
      return json({ state: "connected", error_code: null });
    }
    if (request.method() !== "GET") { unexpected.push(`blocked write ${request.method()} ${path}`); return route.abort(); }
    if (!path.startsWith("/api/")) return route.continue();
    if (path === "/api/v1/model-settings") return readFailure ? route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "mock-sensitive-upstream-detail" }) }) : json({ state: configured ? "configured" : "not_configured", error_code: null });
    if (path === "/api/v1/projects") return json([{ ...workspace, latest_run: null, has_playable_revision: false }]);
    if (path === `/api/v1/projects/${projectId}`) return json(workspace);
    if (path.endsWith("/studio")) return json(saved);
    if (path.endsWith("/classical-source")) return json(classicalSource);
    if (path === "/api/v1/piano-capability") return json({ available: true, pedal_supported: false, release_triggers_supported: false, render_profile: arrangement.render_profile, semantic_generation: { configuration: configured ? "configured" : "not_configured", reason_code: configured ? null : "MODEL_NOT_CONFIGURED" } });
    if (path === "/api/v1/sound-catalog" || path === "/api/v1/classical-scores") return json([]);
    unexpected.push(`unmocked ${path}`); return route.fulfill({ status: 404, body: "Unmocked fixture request" });
  });

  await run("unconfigured-default-no-check", async () => {
    await settings(false); await idle();
    assert(await page.getByRole("button", { name: "测试连接", exact: true }).isDisabled());
    assert.equal(await page.locator("input").count(), 0);
    assert.equal(checks(), 0);
    assert.equal(await page.locator(".shell-more").evaluate(element => element.open), false);
    await screenshot("01-unconfigured-desktop");
  });
  await run("configured-remains-untested", async () => {
    await settings(true); await idle();
    assert(await page.getByRole("button", { name: "测试连接", exact: true }).isEnabled());
    assert.equal(checks(), 0);
    await screenshot("02-configured-desktop");
  });
  await run("explicit-success-and-refresh", async () => {
    const before = checks(); checkMode = "connected";
    await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("连接成功");
    assert.equal(checks(), before + 1);
    await page.getByText(/未验证生成能力、余额或 Worker 配置/).waitFor();
    await screenshot("03-check-success");
    await page.getByRole("button", { name: "刷新配置状态" }).click(); await status("已配置 · 未测试"); await idle();
    assert.equal(checks(), before + 1);
  });
  await run("authentication-failure-and-manual-retry", async () => {
    const before = checks(); checkMode = "auth";
    await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("连接失败");
    await page.getByText(/密钥无效或没有访问权限/).waitFor(); await idle();
    assert.equal(checks(), before + 1);
    await screenshot("04-authentication-failure");
    checkMode = "connected";
    await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("连接成功");
    assert.equal(checks(), before + 2);
  });
  await run("provider-timeout-state", async () => {
    checkMode = "timeout"; const before = checks();
    await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("连接失败");
    await page.getByText(/无法连接 DeepSeek/).waitFor(); await idle();
    assert.equal(checks(), before + 1);
    assert(await page.getByRole("button", { name: "测试连接", exact: true }).isEnabled());
  });
  await run("local-transport-timeout-no-automatic-retry", async () => {
    checkMode = "network-error"; const before = checks();
    await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("检测未完成"); await idle();
    assert.equal(checks(), before + 1);
    await screenshot("05-transport-timeout");
  });
  await run("pending-duplicate-clicks-disabled", async () => {
    await settings(true); checkMode = "gate"; gate = defer();
    const button = page.getByRole("button", { name: "测试连接", exact: true }), before = checks();
    await button.click(); await status("正在测试连接…");
    assert(await button.isDisabled()); assert(await page.getByRole("button", { name: "刷新配置状态" }).isDisabled());
    const box = await button.boundingBox(); assert(box);
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2, { clickCount: 2 });
    await page.keyboard.press("Enter");
    assert.equal(checks(), before + 1);
    await screenshot("06-pending-single-request");
    gate.release(); await status("连接成功"); assert.equal(checks(), before + 1);
  });
  await run("late-response-after-navigation-does-not-label-new-page", async () => {
    await settings(true); checkMode = "gate"; gate = defer(); const before = checks();
    await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("正在测试连接…");
    await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "作品", exact: true }).click();
    await page.getByLabel("作品列表").waitFor();
    await page.goBack();
    await status("已配置 · 未测试");
    await headingClear();
    const response = page.waitForResponse(r => r.url().endsWith("/api/v1/model-settings/check"));
    gate.release(); await (await response).finished(); await idle();
    await status("已配置 · 未测试");
    assert.equal(await page.getByText("连接成功", { exact: true }).count(), 0);
    assert.equal(checks(), before + 1);
    await screenshot("07-return-after-late-response");
  });
  await run("cleared-and-restarted-fixture-state", async () => {
    checkMode = "connected"; await page.getByRole("button", { name: "测试连接", exact: true }).click(); await status("连接成功");
    const before = checks(); configured = false;
    await page.getByRole("button", { name: "刷新配置状态" }).click(); await status("未配置"); await idle();
    assert(await page.getByRole("button", { name: "测试连接", exact: true }).isDisabled());
    assert.equal(checks(), before);
    await page.locator("summary").filter({ hasText: "停用或清除 Key" }).click();
    await page.getByText("python3 scripts/configure_deepseek.py --clear", { exact: true }).waitFor();
  });
  await run("read-error-is-not-missing-key-and-recovery", async () => {
    readFailure = true; const before = checks();
    await page.getByRole("button", { name: "刷新配置状态" }).click(); await status("无法读取配置状态"); await idle();
    assert.equal(await page.getByText("mock-sensitive-upstream-detail", { exact: true }).count(), 0);
    assert(await page.getByRole("button", { name: "测试连接", exact: true }).isDisabled());
    readFailure = false; configured = true;
    await page.getByRole("button", { name: "刷新配置状态" }).click(); await status("已配置 · 未测试");
    assert.equal(checks(), before);
  });
  await run("studio-configuration-link-and-keyboard-navigation", async () => {
    configured = false; const before = checks();
    await page.goto(`${origin}/projects/${projectId}/studio/${revisionId}`, { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: workspace.name, exact: true }).waitFor();
    await headingClear();
    await page.locator(".studio-inspector-disclosure > summary").click();
    const link = page.getByRole("link", { name: "配置 API Key", exact: true }); await link.waitFor();
    assert.equal(await link.getAttribute("href"), "/settings");
    await screenshot("08-studio-configuration-entry");
    await link.focus(); await page.keyboard.press("Enter"); await status("未配置"); await idle();
    assert.equal(checks(), before);
  });
  await run("same-path-query-preserves-scroll", async () => {
    configured = false; const before = checks();
    await page.setViewportSize({ width: 1440, height: 700 });
    await page.goto(`${origin}/projects/${projectId}/studio/${revisionId}`);
    await page.getByRole("heading", { name: workspace.name, exact: true }).waitFor();
    const tab = page.getByRole("tab", { name: "音色库", exact: true });
    await idle();
    const layout = await tab.evaluate(element => ({ bottom: element.getBoundingClientRect().bottom + scrollY, viewport: innerHeight, current: scrollY, max: document.documentElement.scrollHeight - innerHeight }));
    const target = Math.max(0, layout.bottom - layout.viewport + 16);
    assert(target > 0 && target < layout.max - 16, `query scroll probe cannot fit: ${JSON.stringify(layout)}`);
    await page.mouse.wheel(0, target - layout.current);
    await page.waitForFunction(y => Math.abs(scrollY - y) <= 1, target);
    const scrollBefore = await page.evaluate(() => scrollY);
    const maxBefore = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    await tab.click(); await page.waitForURL(url => url.searchParams.get("panel") === "library"); await idle();
    const scrollAfter = await page.evaluate(() => scrollY);
    const maxAfter = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
    assert(Math.abs(scrollAfter - scrollBefore) <= 1, `same pathname query changed scroll: ${JSON.stringify({scrollBefore, scrollAfter, maxBefore, maxAfter})}`);
    assert.equal(checks(), before); return { scroll_before: scrollBefore, scroll_after: scrollAfter, max_before: maxBefore, max_after: maxAfter };
  });
  await run("narrow-settings-discoverability", async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(origin, { waitUntil: "domcontentloaded" }); await page.getByLabel("作品列表").waitFor();
    const link = page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "设置", exact: true });
    const box = await geometry(link); assert(box.x >= 0 && box.x + box.width <= 390 && box.hit);
    const before = checks(); await link.click(); await status("未配置"); await headingClear(); await idle();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert(overflow <= 1); assert.equal(checks(), before);
    await screenshot("09-settings-narrow-390"); return { link: box, horizontal_overflow_px: overflow };
  });
  await run("narrow-studio-entry", async () => {
    const before = checks(); await page.goto(`${origin}/projects/${projectId}/studio/${revisionId}`);
    await page.getByRole("heading", { name: workspace.name, exact: true }).waitFor();
    await headingClear();
    await page.locator(".studio-inspector-disclosure > summary").click();
    const link = page.getByRole("link", { name: "配置 API Key", exact: true }); await link.scrollIntoViewIfNeeded();
    const box = await geometry(link); assert(box.x >= 0 && box.x + box.width <= 390 && box.hit);
    await screenshot("10-studio-entry-narrow-390");
    await link.click(); await status("未配置"); assert.equal(checks(), before); return { link: box };
  });
  assert.deepEqual(errors, []); assert.deepEqual(unexpected, []);
  console.log(`PASS ${cases.length} settings browser scenarios; no real backend or model requests.`);
} finally {
  gate?.release();
  await browser?.close();
  await server.close();
  await writeFile(resolve(output, "evidence.json"), JSON.stringify({ captured_at: new Date().toISOString(), from_case: fromCase ?? null, fixture: "synthetic product-ui + pianoEqTestFixture; no real Key/audio/user project", origin, check_count: checkCount, cases, captureGeometry, errors, unexpected, requests, cleanup: "own browser and Vite closed" }, null, 2));
  console.log("Own browser and Vite stopped.");
}
