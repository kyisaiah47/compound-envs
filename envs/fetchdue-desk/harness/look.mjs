/* RULE 2, AS A MEASUREMENT, AND ON THIS PRODUCT IT IS THE FINDING THAT DECIDED THE WHOLE TASKSET.
 *
 * unemploy's `workspaceSlices()` returns hardcoded empty arrays for six of its seven collections
 * whenever the account is not the demo account, so rows that exist in the database never reach a
 * screen and a browser task against them is impossible. This script asks FetchDue the same
 * question by DRIVING THE PAGE with the captured session and printing what `/` actually rendered.
 *
 * FetchDue's answer is the opposite shape and just as decisive. The console DOES draw a real
 * account's own rows: src/lib/tenant.ts reads every collection through the service role client
 * with a hand written `user_id` filter, and `/` picks that book whenever there is a session. What
 * it does NOT carry is a single control that writes anything. Every button on a row is wired to
 * `onAct={() => setNotice(readOnly)}`, and for a signed-in customer `readOnly` is the product's
 * own sentence, page.tsx's NOT_WIRED constant. So there is no browser task in this environment,
 * and that is a fact about the product rather than a limitation of the harness. Every task is an
 * API task, and the README says so.
 *
 *   node harness/look.mjs        # prints what the console drew, and shoots it
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3757";
const SESSION = path.join(HERE, "session.json");

/* `?show=` is the console's own filter and the ids come from the product's own redirect table,
 * src/app/dashboard/[[...view]]/route.ts, not from a guess. Every retired /dashboard view that
 * named a STATE of a row 308s onto one of these. */
const VIEWS = [
  ["", "the whole river"],
  ["?show=waiting", "waiting on you"],
  ["?show=window", "inside the undo window"],
  ["?show=record", "the record"],
];

async function main() {
  if (!fs.existsSync(SESSION)) throw new Error("no session.json; run harness/signin.mjs first");
  const { cookies, email } = JSON.parse(fs.readFileSync(SESSION, "utf-8"));

  const browser = await launchSafe(puppeteer, { headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1400 });
  try {
    await browser.setCookie(...cookies);
    console.log(`account ${email}`);

    for (const [q, label] of VIEWS) {
      await page.goto(`${APP}/${q}`, { waitUntil: "networkidle2", timeout: 90000 });
      const drawn = await page.evaluate(() => {
        const rows = [...document.querySelectorAll("section.row")].map((el) => ({
          text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 150),
          controls: [...el.querySelectorAll("button.btn")].map((b) => b.innerText.trim()),
        }));
        return {
          rows,
          rowCount: rows.length,
          masthead: (document.querySelector(".lede__h")?.innerText || "").trim(),
          /* The tenant's own names, which the cut demo book does not carry. */
          hasOwnClients: /Westbourne Fitout/.test(document.body.innerText),
          hasOwnNumbers: /INV-2214/.test(document.body.innerText),
          /* The demo book's read-only sentence, and the signed-in one. Only one may appear. */
          demoSentence: /demo workspace is read-only/i.test(document.body.innerText),
          notWired: /not wired here yet/i.test(document.body.innerText),
          /* EVERY control on the page, and what each one is wired to. */
          buttons: [...document.querySelectorAll("button.btn, a.btn")].map((b) => b.innerText.trim()),
        };
      });
      console.log(`\n${APP}/${q}   (${label})`);
      console.log(`  drew ${drawn.rowCount} row(s); own client names: ${drawn.hasOwnClients}; own invoice numbers: ${drawn.hasOwnNumbers}`);
      console.log(`  band: ${drawn.masthead}`);
      for (const r of drawn.rows.slice(0, 6)) {
        console.log(`    ${r.text}`);
        if (r.controls.length) console.log(`      controls: ${JSON.stringify(r.controls)}`);
      }
      if (drawn.rowCount > 6) console.log(`    ... and ${drawn.rowCount - 6} more`);
      console.log(`  every control on the page: ${JSON.stringify([...new Set(drawn.buttons)])}`);
      console.log(`  demo read-only sentence: ${drawn.demoSentence}; signed-in "not wired" sentence: ${drawn.notWired}`);
      const shot = path.join(HERE, `look${q ? q.replace(/[?=]/g, "-") : "-river"}.png`);
      await page.screenshot({ path: shot, fullPage: false });
      console.log(`  shot -> ${path.relative(process.cwd(), shot)}`);
    }

    /* THE CONTROLS, PRESSED. A screenshot cannot tell a live button from a dead one, so the row
     * the console opens by default is found, its network is watched, and its primary control is
     * actually clicked. The console opens the first waiting or window row itself, so nothing is
     * toggled first: toggling would close it and there would be no control to press. */
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 90000 });
    const calls = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/")) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
    });
    const before = await page.evaluate(() => {
      const row = document.querySelector('section.row[data-open="true"]');
      return {
        found: Boolean(row),
        ref: row ? (row.innerText || "").split("\n")[0].slice(0, 60) : null,
        controls: row ? [...row.querySelectorAll("button.btn")].map((b) => b.innerText.trim()) : [],
      };
    });
    await page.evaluate(() => {
      const row = document.querySelector('section.row[data-open="true"]');
      const btn = row && row.querySelector("button.btn");
      if (btn) btn.click();
    });
    await new Promise((r) => setTimeout(r, 1500));
    const after = await page.evaluate(() => ({
      notice: (document.querySelector('section.row[data-open="true"] .readonly')?.innerText || "").trim(),
    }));
    console.log(`\npressed the primary control on the row the console opened itself`);
    console.log(`  row: ${before.ref}`);
    console.log(`  controls on it: ${JSON.stringify(before.controls)}`);
    console.log(`  requests to /api/ that the press caused: ${JSON.stringify(calls)}`);
    console.log(`  what the row answered: ${JSON.stringify(after.notice)}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
