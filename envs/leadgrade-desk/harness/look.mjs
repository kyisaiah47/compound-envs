/* Open the console as the fixture's REAL signed-in account and report what each view renders.
 *
 * ⛔ THIS IS RULE 2, AND IT IS A MEASUREMENT, NOT A READ OF THE SOURCE. Several products in this
 * estate return hardcoded empty collections for any account that is not their demo account, and
 * the code that does it reads as perfectly ordinary. A task whose rows never reach the screen
 * cannot be a browser task, and the only way to know is to drive the page.
 *
 * LeadGrade's console is the site ROOT with a `?view=` query, not a /dashboard tree: /dashboard
 * and /dashboard/<view> are 308 redirects into it (src/app/dashboard/route.ts). Signed out, and
 * for anyone carrying the `lg_demo` cookie, `/` renders the DEMO BOOK, which looks like a real
 * book. So every assertion below is on a row this fixture owns and the demo book does not.
 *
 *   node harness/look.mjs            # screenshots + a per-view count
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const APP = process.env.DESK_APP_URL || session.appUrl || "http://127.0.0.1:3753";

/* ⛔ THE FOUR VIEW IDS ARE READ OFF `src/lib/register.ts`, NEVER GUESSED. `VIEWS` declares
 * queue, leads, record and rails, and `resolveView()` sends anything else to `queue`. The first
 * cut of this file walked ?view=writes, ?view=ledger and ?view=passes, and all three rendered the
 * queue: five lead rows on every one of them, which read as five pages of evidence and was one
 * page shown four times. */
const VIEWS = [
  ["queue", "/"],
  ["leads", "/?view=leads"],
  ["record", "/?view=record"],
  ["rails", "/?view=rails"],
];

/* Rows this fixture owns and the demo book cannot contain. If one of these is on the page, the
 * page is the tenant's own book. */
const OURS = ["Ardenhall", "Lowfield", "Harlow Instruments", "Brightfell", "Stenholm"];

const browser = await launchSafe(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  await browser.setCookie(...session.cookies);

  for (const [name, route] of VIEWS) {
    await page.goto(`${APP}${route}`, { waitUntil: "networkidle2", timeout: 60000 });
    await new Promise((r) => setTimeout(r, 700));
    const seen = await page.evaluate((ours) => {
      const text = document.body.innerText;
      return {
        url: location.href,
        leadRows: document.querySelectorAll(".row-head").length,
        ledgerRows: document.querySelectorAll(".rec").length,
        passRows: document.querySelectorAll(".doc-table-wrap tbody tr").length,
        acts: [...document.querySelectorAll("button.act")].map((b) => b.innerText.trim()).filter(Boolean),
        ours: ours.filter((o) => text.includes(o)),
        text: text.replace(/\s+/g, " ").slice(0, 620),
      };
    }, OURS);
    await page.screenshot({ path: path.join(HERE, `look-${name}.png`), fullPage: true });
    console.log(`\n== ${name}  ${seen.url}`);
    console.log(`   lead rows: ${seen.leadRows}, ledger rows: ${seen.ledgerRows}, pass rows: ${seen.passRows}`);
    console.log(`   this tenant's own names on the page: ${seen.ours.join(", ") || "(none)"}`);
    if (seen.acts.length) console.log(`   controls: ${[...new Set(seen.acts)].join(" | ")}`);
    console.log(`   text: ${seen.text}`);
  }
} finally {
  await browser.close();
}
