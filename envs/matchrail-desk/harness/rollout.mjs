/* The honest browser rollout for `approve-the-price-correction`.
 *
 * It drives the real console with the captured session and approves the correction MatchRail
 * drafted for BILL-8801, through the product's own control, which POSTs /api/corrections.
 * Nothing here writes to the database.
 *
 * ⛔ RULE 7, AND THIS PAGE IS THE WORST CASE OF IT IN THE ESTATE SO FAR. `button.mr-act` matches
 * the primary control of every open exception, and the queue carries TWO Calder Steel & Fastener
 * rows whose primary button reads the identical words, "Re-price the line and post it". The
 * larger of the two, BILL-8802, sorts FIRST, so `document.querySelector(".mr-act")` is the wrong
 * bill. Every control below is addressed inside the `.mr-row` whose `.who em` carries the bill
 * number, and the script asserts the count it found before it clicks anything.
 *
 *   node harness/rollout.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3755";
const SESSION = path.join(HERE, "session.json");
const BILL = process.env.DESK_BILL || "BILL-8801";

async function main() {
  if (!fs.existsSync(SESSION)) throw new Error("no session.json; run harness/signin.mjs first");
  const { cookies } = JSON.parse(fs.readFileSync(SESSION, "utf-8"));

  const browser = await launchSafe(puppeteer, { headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  try {
    page.on("pageerror", (e) => console.error(`  page error: ${e.message}`));
    await browser.setCookie(...cookies);
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 90000 });
    await page.waitForSelector(".mr-row", { timeout: 30000 });

    const shape = await page.evaluate((bill) => {
      const rows = [...document.querySelectorAll(".mr-row")];
      return {
        rows: rows.length,
        allActs: document.querySelectorAll(".mr-act").length,
        matching: rows.filter((r) => (r.querySelector(".who em")?.textContent || "").trim() === bill).length,
        order: rows.map((r) => (r.querySelector(".who em")?.textContent || "").trim()),
      };
    }, BILL);
    console.log(`  queue order ${JSON.stringify(shape.order)}`);
    console.log(`  ${shape.allActs} .mr-act control(s) on the page; ${shape.matching} row(s) carry ${BILL}`);
    if (shape.matching !== 1) throw new Error(`${shape.matching} rows carry ${BILL}; the selector is not unique`);

    // Open the row this task is about. The first waiting row opens on arrival and it is not ours.
    await page.evaluate((bill) => {
      const row = [...document.querySelectorAll(".mr-row")].find(
        (r) => (r.querySelector(".who em")?.textContent || "").trim() === bill,
      );
      if (!row.hasAttribute("data-open")) row.querySelector(".mr-rowhead").click();
    }, BILL);
    await new Promise((r) => setTimeout(r, 600));

    const label = await page.evaluate((bill) => {
      const row = [...document.querySelectorAll(".mr-row")].find(
        (r) => (r.querySelector(".who em")?.textContent || "").trim() === bill,
      );
      return row.querySelector('.mr-act[data-primary="1"]')?.textContent?.trim() ?? null;
    }, BILL);
    if (!label) throw new Error(`${BILL} has no drafted correction control`);
    console.log(`  approving through "${label}"`);

    const call = page.waitForResponse((r) => r.url().includes("/api/corrections"), { timeout: 30000 });
    await page.evaluate((bill) => {
      const row = [...document.querySelectorAll(".mr-row")].find(
        (r) => (r.querySelector(".who em")?.textContent || "").trim() === bill,
      );
      row.querySelector('.mr-act[data-primary="1"]').click();
    }, BILL);
    const res = await call;
    console.log(`  POST /api/corrections -> ${res.status()}`);

    await new Promise((r) => setTimeout(r, 1200));
    const after = await page.evaluate((bill) => {
      const row = [...document.querySelectorAll(".mr-row")].find(
        (r) => (r.querySelector(".who em")?.textContent || "").trim() === bill,
      );
      return {
        state: row.getAttribute("data-state"),
        said: row.querySelector(".mr-window, .mr-held")?.textContent?.trim()?.slice(0, 120) ?? null,
        note: row.querySelector(".mr-readonly")?.textContent?.trim() ?? null,
      };
    }, BILL);
    console.log(`  the row now reads [${after.state}] ${after.said ?? after.note ?? ""}`);
    await page.screenshot({ path: path.join(HERE, "rollout-end.png") });
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(String(err.message || err));
  process.exit(1);
});
