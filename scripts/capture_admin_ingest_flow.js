#!/usr/bin/env node
/* eslint-disable no-console */
const fs = require("fs");
const path = require("path");

function nowStamp() {
  const d = new Date();
  const pad = (v) => String(v).padStart(2, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(
    d.getSeconds()
  )}`;
}

function parseArgs(argv) {
  const args = {
    baseUrl: "http://localhost:3000",
    outDir: `/tmp/oncoai_admin_ingest_screens_${nowStamp()}`,
  };
  for (let i = 2; i < argv.length; i += 1) {
    const raw = argv[i];
    if (!raw.startsWith("--")) continue;
    const key = raw.slice(2);
    const value = argv[i + 1] && !argv[i + 1].startsWith("--") ? argv[++i] : "true";
    if (key === "base-url") args.baseUrl = value;
    if (key === "out-dir") args.outDir = value;
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv);
  let playwright;
  try {
    playwright = require("playwright");
  } catch (err) {
    console.error(
      JSON.stringify(
        {
          error: "playwright_not_installed",
          message:
            "Install Playwright in frontend workspace: `cd frontend && npm i -D playwright && npx playwright install chromium`",
          details: err && err.message ? err.message : String(err),
        },
        null,
        2
      )
    );
    process.exit(2);
  }

  const outDir = path.resolve(args.outDir);
  fs.mkdirSync(outDir, { recursive: true });
  const manifest = [];
  const browser = await playwright.chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  const page = await context.newPage();

  async function shot(name, title) {
    const filename = `${String(manifest.length + 1).padStart(2, "0")}_${name}.png`;
    const full = path.join(outDir, filename);
    await page.screenshot({ path: full, fullPage: true });
    manifest.push({ step: manifest.length + 1, title, file: filename, captured_at: new Date().toISOString() });
    console.log(`captured: ${filename}`);
  }

  try {
    await page.goto(`${args.baseUrl}/`, { waitUntil: "networkidle" });
    await shot("login", "Login screen");

    const adminLink = page.getByRole("link", { name: "Войти как администратор" });
    if (await adminLink.count()) {
      await adminLink.first().click();
      await page.waitForLoadState("networkidle");
    }

    await page.goto(`${args.baseUrl}/admin?tab=docs`, { waitUntil: "networkidle" });
    await shot("admin_docs_before_cleanup", "Admin docs tab before cleanup");

    const dryRunBtn = page.getByRole("button", { name: "Dry-run очистки" });
    if (await dryRunBtn.count()) {
      await dryRunBtn.first().click();
      await page.waitForTimeout(1200);
      await shot("cleanup_dry_run", "Cleanup dry-run result");
    }

    page.on("dialog", async (dialog) => {
      await dialog.accept();
    });
    const applyBtn = page.getByRole("button", { name: "Применить очистку" });
    if (await applyBtn.count()) {
      await applyBtn.first().click();
      await page.waitForTimeout(1500);
      await shot("cleanup_apply", "Cleanup apply result");
    }

    await page.goto(`${args.baseUrl}/admin?tab=docs`, { waitUntil: "networkidle" });
    await shot("upload_form", "Upload form with source_url/doc_kind");

    await page.goto(`${args.baseUrl}/admin?tab=sync`, { waitUntil: "networkidle" });
    await shot("sync_tab", "Sync tab snapshot");

    await page.goto(`${args.baseUrl}/admin?tab=docs`, { waitUntil: "networkidle" });
    await shot("guideline_table", "Guideline table snapshot");

    await page.goto(`${args.baseUrl}/admin?tab=references`, { waitUntil: "networkidle" });
    await shot("references_tab", "References tab (MKB10)");
  } finally {
    await browser.close();
  }

  const manifestPath = path.join(outDir, "manifest.json");
  fs.writeFileSync(manifestPath, JSON.stringify({ base_url: args.baseUrl, screenshots: manifest }, null, 2), "utf-8");
  console.log(JSON.stringify({ status: "ok", out_dir: outDir, manifest: manifestPath }, null, 2));
}

main().catch((err) => {
  console.error(
    JSON.stringify(
      {
        error: "capture_failed",
        message: err && err.message ? err.message : String(err),
      },
      null,
      2
    )
  );
  process.exit(1);
});
