/* The honest rollout for each task. It drives the REAL running product, never the database.
 *
 *   node rollout.mjs <task-id>
 *
 * THE LETTER FORM IS ON /letter AND NOWHERE ELSE, AND THE PAGES THAT ARE NOT /letter CARRY A
 * DIFFERENT SUBMIT BUTTON (rule 7). Measured with harness/look.mjs at 1440px against the running
 * production build:
 *
 *     /         form.search       GET /all   "Ask the journal"   0 email inputs
 *     /archive  form.search       GET /all   "Ask the journal"   0 email inputs
 *     /all      form.search       GET /all   "Ask the journal"   0 email inputs
 *     /letter   form.letter-form  (fetch)    "Subscribe"         1 email input
 *
 * So a rollout that opened the home page and clicked its only `button[type=submit]` would navigate
 * to the archive, nothing would error, and no address would ever be stored. This one opens
 * /letter, finds the form by its own class, clicks the button inside THAT form, and then asserts
 * from inside the page that exactly one POST was made and that it went to /api/subscribe on this
 * origin.
 *
 * IT SUBMITS ONCE, AND ONCE IS ALSO WHAT THE PRODUCT CAN GET RIGHT. `publication_subscribers_
 * unique` is a plain unique index over (publication, email) and neither column is nullable, so a
 * repeat merges onto the existing row rather than writing a second one.
 */
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3317";

/* The people in the fixture's prompts. Every address is invented and every domain is `.example`.
 * Typed with capitals and surrounding space on purpose: LetterForm trims and lowercases before it
 * posts and the route does it again, so a row carrying the typed form was written past both. */
export const NEW_READER_AS_TYPED = "  Wynn.Calderbank@Thurloe-Assay.example ";
export const LEAVING_READER_TOKEN = "0000fd01-0000-4000-8000-00000000fd01";

/** Put a reader on the letter using the site's own form. */
async function putTheReaderOnTheLetter() {
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1200 });
    await page.goto(`${APP}/letter`, { waitUntil: "networkidle2", timeout: 60000 });
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

    /* LetterForm replaces the whole form with `<div class="letter-note gold-note" role="status">`
     * only when the route answered ok. A refusal leaves the form standing with a role="alert"
     * note beside it, so this times out rather than passing quietly. */
    await page.waitForSelector("div.letter-note[role=status]", { timeout: 20000 });
    const said = await page.$eval("div.letter-note[role=status]", (el) => el.textContent.trim());
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
function publishTheJournalLive() {
  return new Promise((resolve, reject) => {
    const proc = spawn(path.join(HERE, "..", "engine", "run.sh"), [], { stdio: "inherit" });
    proc.on("error", reject);
    proc.on("exit", (code) =>
      code === 0 ? resolve() : reject(new Error(`publish exited ${code}`))
    );
  });
}

const TASKS = {
  "put-the-reader-on-the-letter": putTheReaderOnTheLetter,
  "take-the-reader-off-the-letter": takeTheReaderOffTheLetter,
  "publish-the-journal-live": publishTheJournalLive,
};

const id = process.argv[2];
if (!TASKS[id]) {
  console.error(`usage: node rollout.mjs <${Object.keys(TASKS).join("|")}>`);
  process.exit(2);
}
await TASKS[id]();
