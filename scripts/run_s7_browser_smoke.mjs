#!/usr/bin/env node
/** Public S7 portfolio, evidence, Inspector, Export, and mobile acceptance. */

import { chromium } from "playwright";

const WEB_URL = (process.env.MOTIF_FORGE_WEB_URL ?? "http://127.0.0.1:5173").replace(/\/$/, "");
const PROJECT_ID = (process.env.MOTIF_FORGE_S7_PROJECT_ID ?? "").trim();
const RUN_ID = (process.env.MOTIF_FORGE_S7_RUN_ID ?? "").trim();
const REVISION_ID = (process.env.MOTIF_FORGE_S7_REVISION_ID ?? "").trim();
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function invariant(value, message) { if (!value) throw new Error(message); }

async function main() {
  invariant(WEB_URL === "http://127.0.0.1:5173", "S7 browser smoke requires local Web origin");
  invariant([PROJECT_ID, RUN_ID, REVISION_ID].every((value) => UUID.test(value)),
    "set S7 project/run/revision IDs from the deterministic smoke output");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.goto(`${WEB_URL}/about`);
    await page.getByRole("heading", { name: /Brief 到可编辑作品/ }).waitFor();
    await page.goto(`${WEB_URL}/evaluation`);
    await page.getByText("80 / 80").waitFor();
    await page.goto(`${WEB_URL}/runs/${RUN_ID}/inspect`);
    await page.getByRole("heading", { name: "Run Inspector" }).waitFor();
    await page.goto(`${WEB_URL}/projects/${PROJECT_ID}/exports/${REVISION_ID}`);
    await page.getByText("完整可交付").waitFor();
    invariant(await page.locator('[data-testid="export-step"]').count() === 7,
      "S7 Export page did not render the canonical seven steps");
    await page.setViewportSize({ width: 390, height: 844 });
    for (const path of ["/about", "/evaluation", `/runs/${RUN_ID}/inspect`,
      `/projects/${PROJECT_ID}/exports/${REVISION_ID}`]) {
      await page.goto(`${WEB_URL}${path}`);
      invariant(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
        `S7 mobile horizontal overflow at ${path}`);
    }
    console.log(JSON.stringify({ status: "passed", project_id: PROJECT_ID, run_id: RUN_ID }));
  } finally {
    await browser.close();
  }
}

await main();
