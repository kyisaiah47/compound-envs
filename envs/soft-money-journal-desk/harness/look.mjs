/* RULE 2, done by driving the product rather than by reading it.
 *
 *   node look.mjs            # the default: /letter, /archive and /rss.xml at 1440px
 *
 * unemploy's `workspaceSlices()` returned hardcoded empty arrays for six of its seven collections
 * whenever the account was not the demo account, and three graders were written against a
 * workflow that never reaches a screen. This product has no accounts at all, so there is no
 * equivalent function to read. What it has instead is a merge with a committed fallback, and the
 * question that decides the taskset is the same one: DOES A ROW REACH A SURFACE.
 *
 * Three things come out of this and all three are in the README.
 *
 *   1. WHICH CONTROLS ARE ON /letter, because rule 7 says a selector is ambiguous until it is
 *      measured. `parts.tsx` exports a `Search` form whose submit button is a GET to /all; it is
 *      rendered on /, /archive and /all and NOT on /letter.
 *   2. WHETHER THE PAGES MOVE WITH THE TABLE. Run with the table holding this publication's rows
 *      and again with them deleted, and compare the entry counts.
 *   3. WHETHER /rss.xml MOVES WITH THE TABLE, which is the one surface in this product that
 *      imports src/lib/live.ts at all.
 *
 * It measures and prints. It changes nothing.
 */
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3317";

const browser = await launchSafe(puppeteer);
const out = {};
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });

  for (const route of ["/", "/letter", "/archive", "/all"]) {
    await page.goto(`${APP}${route}`, { waitUntil: "networkidle2", timeout: 60000 });
    out[route] = await page.evaluate(() => ({
      forms: [...document.querySelectorAll("form")].map((f) => ({
        className: f.className,
        method: (f.getAttribute("method") || "get").toLowerCase(),
        action: f.getAttribute("action"),
        submits: f.querySelectorAll('button[type="submit"]').length,
        button: f.querySelector('button[type="submit"]')?.textContent?.trim() ?? null,
        fields: [...f.querySelectorAll("input")].map((i) => `${i.type}:${i.name || "(unnamed)"}`),
      })),
      emailInputs: document.querySelectorAll('input[type="email"]').length,
      submitButtons: document.querySelectorAll('button[type="submit"]').length,
      signInControls: document.querySelectorAll(
        'a[href*="sign-in"], a[href*="login"], button[data-testid*="sign"]',
      ).length,
      entryLinks: new Set(
        [...document.querySelectorAll('a[href^="/entry/"]')].map((a) => a.getAttribute("href")),
      ).size,
    }));
  }

  const feed = await (await fetch(`${APP}/rss.xml`)).text();
  out["/rss.xml"] = {
    items: (feed.match(/<item>/g) || []).length,
    firstLink: (feed.match(/<link>([^<]+entry[^<]*)<\/link>/) || [])[1] ?? null,
  };
} finally {
  await browser.close();
}
console.log(JSON.stringify(out, null, 2));
