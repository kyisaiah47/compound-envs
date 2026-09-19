/* RULE 2, MEASURED. What does this product render for a real row rather than for its own frozen
 * sample?
 *
 *   node harness/look.mjs
 *
 * BreachProbe has no accounts, no sign-in and no demo account, so the shape of rule 2 here is not
 * "demo versus real customer" but "the product's frozen sample versus a row in the database".
 * `src/lib/sample.ts` is a hard-coded report served at /report/sample, and `src/content/live.json`
 * is a frozen console the landing draws before anybody scans anything. If the real surfaces drew
 * those instead of the row, no task on this product could be a browser task.
 *
 * It prints what each page actually rendered and writes a screenshot per page, so the answer is a
 * measurement and not a reading of the source.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3851";
const SCAN_DELIVERED = "00000000-0000-4000-8000-0000000f8010";
const VAULTLINE = "http://127.0.0.1:3852";

async function open(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.setRequestInterception(true);
  page.on("request", (req) => {
    let host = "";
    try {
      host = new URL(req.url()).hostname;
    } catch {
      host = "";
    }
    if (host && host !== "127.0.0.1" && host !== "localhost") return void req.abort().catch(() => {});
    req.continue().catch(() => {});
  });
  return page;
}

const shot = (page, name) => page.screenshot({ path: path.join(HERE, `look-${name}.png`), fullPage: false });

const browser = await launchSafe(puppeteer, {});
try {
  // 1. The landing scan bar, before and after a real scan.
  const home = await open(browser);
  await home.goto(`${APP}/`, { waitUntil: "domcontentloaded" });
  await home.waitForSelector('form[data-diagnostic="scan"]', { timeout: 20000 });
  await shot(home, "landing-idle");
  await home.type('form[data-diagnostic="scan"] input[inputmode="url"]', VAULTLINE, { delay: 6 });
  await home.click(".scanbar .own input[type=checkbox]");
  const done = home.waitForResponse((r) => r.url().includes("/api/scan"), { timeout: 120000 });
  await home.click('form[data-diagnostic="scan"] button.go');
  await done;
  await new Promise((r) => setTimeout(r, 1200));
  const console_ = await home.evaluate(() => document.body.innerText);
  await shot(home, "landing-scanned");
  console.log("/ after a real scan");
  console.log("  the host it scanned on screen:", console_.includes("127.0.0.1:3852"));
  console.log("  the grade F on screen        :", /\bF\b/.test(console_));
  console.log("  a finding it actually found  :", console_.toLowerCase().includes("service_role"));

  // 2. /report/<id> for a delivered order that exists only as a row.
  const rep = await open(browser);
  await rep.goto(`${APP}/report/${SCAN_DELIVERED}`, { waitUntil: "domcontentloaded" });
  await new Promise((r) => setTimeout(r, 2500));
  const reportText = await rep.evaluate(() => document.body.innerText);
  await shot(rep, "report");
  console.log(`/report/${SCAN_DELIVERED}`);
  console.log("  the row's own host on screen :", reportText.includes("127.0.0.1:3853"));
  console.log("  it is not the frozen sample  :", !reportText.includes("lovable.app"));

  // 3. /smoke, the second browser surface.
  const smoke = await open(browser);
  await smoke.goto(`${APP}/smoke`, { waitUntil: "domcontentloaded" });
  await smoke.waitForSelector("#smoke form.scanform input[inputmode=url]", { timeout: 20000 });
  await shot(smoke, "smoke");
  console.log("/smoke");
  console.log("  the queue form is on screen  : true");
} finally {
  await browser.close();
}
