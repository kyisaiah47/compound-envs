/* RULE 2, AS A MEASUREMENT. What does the console draw for a REAL signed-in account, rather than
 * for the demo book?
 *
 * unemploy's `workspaceSlices()` returns hardcoded empty arrays for six of its seven collections
 * whenever the account is not the demo account, so rows that exist in the database never reach a
 * screen and a browser task against them is impossible. This script asks MatchRail the same
 * question by DRIVING THE PAGE, restoring the captured session and printing what the queue
 * actually rendered, rather than by reading `_console/read.ts` and concluding it looks fine.
 *
 *   node harness/look.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3755";
const SESSION = path.join(HERE, "session.json");

async function main() {
  if (!fs.existsSync(SESSION)) throw new Error("no session.json; run harness/signin.mjs first");
  const { cookies, email } = JSON.parse(fs.readFileSync(SESSION, "utf-8"));

  const browser = await launchSafe(puppeteer, { headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  try {
    await browser.setCookie(...cookies);
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 90000 });

    const drawn = await page.evaluate(() => {
      const rows = [...document.querySelectorAll(".mr-row")].map((el) => ({
        who: el.querySelector(".who")?.childNodes[0]?.textContent?.trim() ?? null,
        ref: el.querySelector(".who em")?.textContent?.trim() ?? null,
        said: el.querySelector(".said")?.textContent?.trim() ?? null,
        figure: el.querySelector(".fig")?.textContent?.trim() ?? null,
        state: el.getAttribute("data-state"),
        controls: [...el.querySelectorAll(".mr-act")].map((b) => b.textContent.trim()),
        window: el.querySelector(".mr-window, .mr-held")?.textContent?.trim() ?? null,
      }));
      return {
        signedInAs:
          [...document.querySelectorAll("*")]
            .map((n) => n.textContent)
            .find((t) => t && t.includes("@") && t.length < 80) ?? null,
        rows,
        rowCount: rows.length,
        bodyHasDemoWord: /demo book is read-only/i.test(document.body.innerText),
      };
    });

    console.log(`account ${email}`);
    console.log(`the queue drew ${drawn.rowCount} row(s)`);
    for (const r of drawn.rows) {
      console.log(`  [${r.state}] ${r.who} ${r.ref}  ${r.figure}`);
      console.log(`        said: ${r.said}`);
      console.log(`        controls: ${JSON.stringify(r.controls)}${r.window ? `  window: ${r.window}` : ""}`);
    }
    console.log(`read-only demo message on the page: ${drawn.bodyHasDemoWord}`);

    await page.screenshot({ path: path.join(HERE, "look-queue.png"), fullPage: false });
    console.log(`shot -> ${path.relative(process.cwd(), path.join(HERE, "look-queue.png"))}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(String(err.message || err));
  process.exit(1);
});
