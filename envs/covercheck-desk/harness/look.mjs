/* What the console actually renders for a REAL signed-in member.
 *
 * ⛔ THIS EXISTS BECAUSE THE SCHEMA AND THE ROUTES BOTH LIE ABOUT IT. unemploy's console returns
 * hardcoded empty arrays for six of its seven collections whenever the account is not the demo
 * account, so rows written by its routes never appear on any page a customer can open, and that
 * was invisible until somebody drove it as a customer. CoverCheck's `loadConsole()` takes the
 * organisation as an argument and reads the same tables either way, which is the opposite shape,
 * but "it looks like it should work" is not a measurement. This is the measurement.
 *
 *   node harness/look.mjs [?view=review]
 *
 * It prints what the page contains, region by region, and leaves a full-page screenshot beside
 * this file. Desktop width only: 1440x900.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3764";
const QUERY = process.argv[2] || "";
const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

const browser = await launchSafe(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await browser.setCookie(...session.cookies);
  await page.goto(`${APP}/${QUERY}`, { waitUntil: "networkidle2", timeout: 60000 });

  const seen = await page.evaluate(() => {
    const text = (sel) => document.querySelector(sel)?.textContent?.trim() ?? null;
    return {
      marker: text(".marker") ?? text("[class*=marker]"),
      rows: [...document.querySelectorAll(".row, [id^=row-]")].length,
      vendorsNamed: [...document.querySelectorAll("*")]
        .filter((el) => el.children.length === 0 && /Bright Path|Ironwood|Halcyon|Verdant/.test(el.textContent || ""))
        .map((el) => el.textContent.trim())
        .filter((v, i, a) => a.indexOf(v) === i)
        .slice(0, 12),
      drafts: [...document.querySelectorAll(".draft")].map((d) => ({
        id: d.id,
        status: d.dataset.status,
        head: d.querySelector(".draft-subj")?.textContent?.trim() ?? null,
      })),
      tabs: [...document.querySelectorAll('[role="tab"]')].map((t) => t.textContent.trim()),
      fileInputs: document.querySelectorAll('input[type="file"]').length,
      selects: [...document.querySelectorAll("select")].map((s) => ({
        options: [...s.options].map((o) => o.textContent.trim()),
        value: s.selectedOptions[0]?.textContent?.trim() ?? null,
      })),
    };
  });

  console.log(JSON.stringify(seen, null, 2));
  const shot = path.join(HERE, `look${QUERY.replace(/\W+/g, "-")}.png`);
  await page.screenshot({ path: shot, fullPage: true });
  console.log(`\nshot: ${path.relative(process.cwd(), shot)}`);
} finally {
  await browser.close();
}
