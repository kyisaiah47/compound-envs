/* Open the console as the fixture's REAL signed-in account and report what each page renders.
 *
 * ⛔ THIS IS RULE 2, AND IT IS A MEASUREMENT, NOT A READ OF THE SOURCE. Several products in this
 * estate return hardcoded empty collections for any account that is not their demo account, and
 * the code that does it reads as perfectly ordinary. A task whose rows never reach the screen
 * cannot be a browser task, and the only way to know is to drive the page.
 *
 *   node harness/look.mjs            # screenshots + a row count per page
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const APP = process.env.DESK_APP_URL || session.appUrl || "http://127.0.0.1:3769";

const PAGES = [
  ["overview", "/dashboard"],
  ["keys", "/dashboard/keys"],
  ["billing", "/dashboard/billing"],
  ["requests", "/dashboard/requests"],
  ["jobs", "/dashboard/jobs"],
  ["webhooks", "/dashboard/webhooks"],
];

const browser = await launchSafe(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  await browser.setCookie(...session.cookies);

  for (const [name, route] of PAGES) {
    await page.goto(`${APP}${route}`, { waitUntil: "networkidle2", timeout: 60000 });
    await new Promise((r) => setTimeout(r, 900));
    const seen = await page.evaluate(() => ({
      url: location.href,
      rows: document.querySelectorAll("table tbody tr").length,
      selects: [...document.querySelectorAll("select")].map((s) => `${s.id}=${JSON.stringify(s.value)}`),
      inputs: [...document.querySelectorAll("input")].map((i) => `${i.id || i.type}=${JSON.stringify(i.value)}`),
      text: document.body.innerText.replace(/\s+/g, " ").slice(0, 700),
    }));
    await page.screenshot({ path: path.join(HERE, `look-${name}.png`), fullPage: true });
    console.log(`\n== ${name}  ${seen.url}`);
    console.log(`   table rows: ${seen.rows}`);
    if (seen.selects.length) console.log(`   selects: ${seen.selects.join(", ")}`);
    if (seen.inputs.length) console.log(`   inputs: ${seen.inputs.join(", ")}`);
    console.log(`   text: ${seen.text}`);
  }
} finally {
  await browser.close();
}
