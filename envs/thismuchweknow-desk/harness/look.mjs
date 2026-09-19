/* RULE 2, MEASURED: what the running product actually renders, for a real visitor.
 *
 *   node look.mjs [origin]
 *
 * unemploy's `workspaceSlices()` returns hardcoded empty arrays for six of its seven collections
 * whenever the account is not the demo account, so three of its graders were written against a
 * workflow no page could show. This product has no accounts at all, so the equivalent question is
 * asked by driving it at 1440 and counting what is on each route. Two answers came out of this and
 * both decided the taskset:
 *
 *   1. THE LETTER FORM IS ON EXACTLY ONE ROUTE, AND IT IS NOT THE LANDING. `/about` carries it,
 *      under the nav label "The method". The four sibling publications put the same component at
 *      the foot of every page. A rollout written from the siblings drives `/`, finds no email
 *      input, and times out.
 *   2. THE LANDING CARRIES TWO SUBMIT BUTTONS AND NEITHER IS THE LETTER (rule 7). `form.search` is
 *      a GET to `/` and `form.door-head` closes the left rail's dialog. On `/about` there is a
 *      third, inside `form.letter-form`. Clicking the page's first `button[type=submit]` there
 *      runs the search and no address is ever stored.
 *
 * `span.hits` is also shared: `form.search` renders one and `form.letter-form` renders one, and
 * the letter's is where the route's answer is printed. Reading `span.hits` unscoped on /about
 * reads the search box.
 */
import puppeteer from "puppeteer";
import { launchSafe } from "./safe-chrome.mjs";

const APP = process.argv[2] || process.env.DESK_APP_URL || "http://127.0.0.1:3330";
const ROUTES = ["/", "/about", "/stops", "/pictures", "/entry/milgram"];

const browser = await launchSafe(puppeteer);
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });

  console.log(`${APP} at 1440px\n`);
  console.log("route            forms  submits  emailInputs  span.hits  letterForm  entryLinks");
  for (const route of ROUTES) {
    await page.goto(`${APP}${route}`, { waitUntil: "networkidle2", timeout: 60000 });
    const s = await page.evaluate(() => ({
      forms: document.querySelectorAll("form").length,
      submits: document.querySelectorAll('button[type="submit"]').length,
      emails: document.querySelectorAll('input[type="email"]').length,
      hits: document.querySelectorAll("span.hits").length,
      letter: !!document.querySelector("form.letter-form"),
      entries: new Set(
        [...document.querySelectorAll('a[href^="/entry/"]')].map((a) => a.getAttribute("href")),
      ).size,
    }));
    console.log(
      `${route.padEnd(16)} ${String(s.forms).padEnd(6)} ${String(s.submits).padEnd(8)}` +
      ` ${String(s.emails).padEnd(12)} ${String(s.hits).padEnd(10)}` +
      ` ${String(s.letter).padEnd(11)} ${s.entries}`,
    );
  }

  await page.goto(`${APP}/about`, { waitUntil: "networkidle2", timeout: 60000 });
  const forms = await page.evaluate(() =>
    [...document.querySelectorAll("form")].map((f) => ({
      cls: f.className || "(none)",
      method: (f.getAttribute("method") || "post").toLowerCase(),
      action: f.getAttribute("action") || "(js)",
      submits: f.querySelectorAll('button[type="submit"]').length,
      fields: [...f.querySelectorAll("input")].map((i) => `${i.name || "(unnamed)"}:${i.type}`),
    })),
  );
  console.log("\n/about, form by form");
  for (const f of forms) {
    console.log(
      `  .${f.cls.padEnd(14)} ${f.method.toUpperCase().padEnd(6)} ${f.action.padEnd(6)}` +
      ` submits=${f.submits}  fields=[${f.fields.join(", ")}]`,
    );
  }
} finally {
  await browser.close();
}
