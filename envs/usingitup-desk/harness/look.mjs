/* Rule 2, measured by driving the product rather than by reading it.
 *
 *   node look.mjs
 *
 * unemploy has a `workspaceSlices()` that returns hardcoded empty arrays for anything that is not
 * the demo account, so rows written by a correct rollout never reach the screen. usingitup has no
 * accounts at all, so the question here is a different one and it has to be asked the same way:
 * WHAT DOES THE PAGE SHOW, and is any of it evidence that a row exists?
 *
 * Two answers come out of this, and both of them decided the taskset.
 *
 * 1. THE LANDING CARRIES TWO SUBMIT BUTTONS. One belongs to `form.search`, which is a plain GET
 *    to /archive/all; the other belongs to `form.letter-form`. Clicking the page's first submit
 *    navigates to the archive and nothing errors, so the browser rollout addresses the letter
 *    form's own element. That is rule 7 on this product.
 *
 * 2. THE ARCHIVE RENDERS WITH THE TABLE EMPTY. src/lib/live.ts merge() starts from the COMMITTED
 *    archive in src/content/archive.ts and lets live rows override it, so /archive shows all 73
 *    published entries whether or not publication_posts holds a single row. An entry being on the
 *    page is therefore not evidence the publish engine wrote anything, which is rule 3 stated as a
 *    property of this product: the only honest check on task C is the rows.
 */
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3778";

const browser = await launchSafe(puppeteer);
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

  const landing = await page.evaluate(() => ({
    forms: [...document.querySelectorAll("form")].map((f) => ({
      className: f.className,
      action: f.getAttribute("action"),
      method: f.getAttribute("method"),
      fields: [...f.querySelectorAll("input")].map((i) => `${i.name || "?"}:${i.type}`),
      submits: [...f.querySelectorAll('button[type="submit"]')].map((b) =>
        (b.textContent || "").trim() || "(no text)"
      ),
    })),
    emailInputs: document.querySelectorAll('input[type="email"]').length,
    submitButtons: document.querySelectorAll('button[type="submit"]').length,
    honeypots: document.querySelectorAll('input[name="trap"]').length,
    signInControls: document.querySelectorAll(
      'a[href*="sign-in"], a[href*="login"], button[data-auth]'
    ).length,
  }));
  console.log("landing", JSON.stringify(landing, null, 2));

  await page.goto(`${APP}/archive/all`, { waitUntil: "networkidle2", timeout: 60000 });
  const archive = await page.evaluate(() => ({
    entryLinks: document.querySelectorAll('a[href^="/entry/"]').length,
  }));
  console.log("archive", JSON.stringify(archive));
  console.log(
    "NOTE: that count comes from the committed archive merged with whatever rows exist. Empty the" +
      " table and re-run this to see it unchanged."
  );
} finally {
  await browser.close();
}
