/* The honest rollout for each task. It drives the REAL running product, never the database.
 *
 *   node rollout.mjs <task-id>
 *
 * THE LANDING CARRIES TWO SUBMIT BUTTONS AND ONLY ONE OF THEM IS THE LETTER (rule 7).
 * `form.search` is a GET to /archive/all and `form.letter-form` posts to /api/subscribe. Clicking
 * the page's first `button[type=submit]` navigates to the archive, nothing errors, and no address
 * is ever stored. So the rollout finds the letter form by its own class and clicks the button
 * inside THAT form, then asserts from inside the page that exactly one POST was made and that it
 * went to /api/subscribe on this origin.
 *
 * IT SUBMITS ONCE, AND ONCE IS ALSO WHAT THE PRODUCT CAN GET RIGHT. `publication_subscribers_
 * unique` is a plain unique index over (publication, email) and neither column is nullable, so a
 * repeat merges onto the existing row rather than writing a second one. Measured against the
 * running copy on 2026-09-19: a second POST of the same address answered `{"ok":true}` and the
 * table still held one row for her.
 */
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3778";

/* The people in the fixture's prompts. Every address is invented and every domain is `.example`.
 * Typed with capitals and surrounding space on purpose: the route trims and lowercases, so a row
 * carrying the typed form was written past it. */
export const NEW_READER_AS_TYPED = "  Wilhelmina.Sprague@Coldharbour-Wharf.example ";
export const LEAVING_READER_TOKEN = "0000fb01-0000-4000-8000-00000000fb01";

/** Put a reader on the letter using the site's own form. */
async function subscribeFromTheLetterForm() {
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1200 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });
    await page.waitForSelector("form.letter-form input[name=email]", { timeout: 20000 });

    // Record where the page's own requests went, so the assertion is about the request that
    // happened rather than about the confirmation line.
    const posted = [];
    page.on("request", (r) => {
      if (r.method() === "POST") posted.push(r.url());
    });

    await page.type("form.letter-form input[name=email]", NEW_READER_AS_TYPED);
    await page.evaluate(() => {
      const form = document.querySelector("form.letter-form");
      form.querySelector('button[type="submit"]').click();
    });

    // LetterForm replaces the whole form with `<p class="letter-note" role="status">` only when
    // the route answered ok. A failure leaves the form standing with role="alert" beside it, so
    // this times out rather than passing quietly.
    await page.waitForSelector("p.letter-note[role=status]", { timeout: 20000 });
    const said = await page.$eval("p.letter-note[role=status]", (el) => el.textContent.trim());
    const formStillThere = await page.$("form.letter-form");
    if (formStillThere) throw new Error("the form is still on the page, so the route refused it");

    const foreign = posted.filter((u) => !u.startsWith(APP));
    if (foreign.length) throw new Error(`the page posted off-origin: ${foreign.join(", ")}`);
    const ours = posted.filter((u) => u.endsWith("/api/subscribe"));
    if (ours.length !== 1) {
      throw new Error(`expected one POST to /api/subscribe, saw ${posted.length}: ${posted.join(", ")}`);
    }
    console.log(`submitted once, ${ours[0]}`);
    console.log(`the page said: ${said}`);
  } finally {
    await browser.close();
  }
}

/** Follow the unsubscribe link from a letter and confirm it, the way a reader does.
 *
 * The link is what compound-ops/letters/send-letter.py puts in the footer of every letter and in
 * the List-Unsubscribe header: `<site>/api/subscribe/unsubscribe?token=<that reader's token>`.
 * GET renders a one button confirmation page, because mail scanners follow links; POST is what
 * takes the address off. The page has exactly one form and one button. */
async function takeTheReaderOffTheLetter() {
  const link = `${APP}/api/subscribe/unsubscribe?token=${LEAVING_READER_TOKEN}`;
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1200 });
    await page.goto(link, { waitUntil: "networkidle2", timeout: 60000 });
    const heading = await page.$eval("h1", (el) => el.textContent.trim());
    if (heading !== "One more click") {
      throw new Error(`the confirmation page said ${JSON.stringify(heading)}`);
    }
    await Promise.all([
      page.waitForNavigation({ waitUntil: "networkidle2", timeout: 30000 }),
      page.click('form button[type="submit"]'),
    ]);
    const after = await page.$eval("h1", (el) => el.textContent.trim());
    if (after !== "You're off the list") {
      throw new Error(`after confirming, the page said ${JSON.stringify(after)}`);
    }
    console.log(`confirmed at ${link}`);
    console.log(`the page said: ${after}`);
  } finally {
    await browser.close();
  }
}

/** Run the nightly publish. Same entry point sync-site.sh calls at 21:30, scoped to this site. */
function publishTheInventoryLive() {
  return new Promise((resolve, reject) => {
    const proc = spawn(path.join(HERE, "..", "engine", "run.sh"), [], { stdio: "inherit" });
    proc.on("error", reject);
    proc.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`publish exited ${code}`))
    );
  });
}

const TASKS = {
  "subscribe-from-the-letter-form": subscribeFromTheLetterForm,
  "take-the-reader-off-the-letter": takeTheReaderOffTheLetter,
  "publish-the-inventory-live": publishTheInventoryLive,
};

const id = process.argv[2];
if (!TASKS[id]) {
  console.error(`usage: node rollout.mjs <${Object.keys(TASKS).join("|")}>`);
  process.exit(2);
}
await TASKS[id]();
