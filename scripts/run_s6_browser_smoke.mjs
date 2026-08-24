#!/usr/bin/env node
/** Local browser acceptance for selection edit, Preview approval, refresh, and narrow layout. */

import { chromium } from "playwright";

const WEB_URL = (process.env.MOTIF_FORGE_WEB_URL ?? "http://127.0.0.1:5173").replace(/\/$/, "");
const PROJECT_ID = (process.env.MOTIF_FORGE_S6_PROJECT_ID ?? "").trim();
const REVISION_ID = (process.env.MOTIF_FORGE_S6_REVISION_ID ?? "").trim();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function invariant(value, message) { if (!value) throw new Error(message); }

async function main() {
  invariant(WEB_URL === "http://127.0.0.1:5173", "S6 browser smoke requires local Web origin");
  invariant(UUID.test(PROJECT_ID) && UUID.test(REVISION_ID),
    "set S6 project/revision IDs from deterministic smoke output");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.goto(`${WEB_URL}/projects/${PROJECT_ID}/studio/${REVISION_ID}`);
    await page.getByRole("heading", { name: "AI 选区编辑" }).waitFor();
    const clip = page.getByRole("button", { name: /Clip/ }).first();
    invariant(await clip.count() > 0, "S6 browser fixture needs one visible Clip selection");
    await clip.click();
    await page.getByLabel("AI 编辑要求").fill("把这里的 Pad 降低 2 dB");
    await page.getByRole("button", { name: "运行选区编辑" }).click();
    await page.getByText("已提交新 Revision").waitFor({ timeout: 120_000 });
    await page.reload();
    await page.getByRole("heading", { name: "AI 选区编辑" }).waitFor();
    invariant(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      "desktop Studio has horizontal overflow");
    await page.setViewportSize({ width: 390, height: 844 });
    invariant(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      "mobile Studio has horizontal overflow");
    invariant(!(await page.getByRole("button", { name: "运行选区编辑" }).isVisible()),
      "mobile must be review-only for AI edit creation");
    console.log(JSON.stringify({ status: "passed", project_id: PROJECT_ID }));
  } finally {
    await browser.close();
  }
}

await main();
