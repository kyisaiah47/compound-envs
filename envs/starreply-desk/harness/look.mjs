/* What the console actually renders for THIS signed-in account.
 *
 * ⛔ RULE 2. Several products in this estate hand any non-demo session a hardcoded empty book, so
 * rows that exist in the database never reach a screen and a task written against them cannot be
 * a browser task. This is the measurement rather than a reading of the code: it restores the
 * captured session, opens `/`, and prints the queue rows, the controls on the open card and the
 * bar the page drew.
 *
 *   node harness/look.mjs [view]        # writes harness/look-<view>.png
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3752";
const view = process.argv[2] || "";

const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

const browser = await launchSafe(puppeteer, { headless: true });
try {
  await browser.setCookie(...session.cookies);
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1600 });
  await page.goto(`${APP}/${view}`, { waitUntil: "networkidle2", timeout: 60000 });
  await new Promise((r) => setTimeout(r, 1200));

  const seen = await page.evaluate(() => {
    const text = (el) => (el?.textContent || "").replace(/\s+/g, " ").trim();
    return {
      title: document.title,
      rows: [...document.querySelectorAll(".fxR")].map((el) => text(el).slice(0, 140)),
      openCard: text(document.querySelector(".fxX")).slice(0, 700),
      controls: [...document.querySelectorAll("button, a.ghost, a.cta")]
        .map((b) => text(b))
        .filter(Boolean)
        .slice(0, 40),
      bodyHead: text(document.body).slice(0, 900),
    };
  });
  console.log(JSON.stringify(seen, null, 2));
  const shot = path.join(HERE, `look-${view.replace(/\W+/g, "") || "queue"}.png`);
  await page.screenshot({ path: shot, fullPage: false });
  console.log(`\nshot -> ${path.relative(process.cwd(), shot)}`);
} finally {
  await browser.close();
}
