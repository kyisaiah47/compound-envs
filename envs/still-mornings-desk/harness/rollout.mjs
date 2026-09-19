/* The honest rollout for each task. It drives the REAL running product, never the database.
 *
 *   node rollout.mjs <task-id>
 *
 * RULE 7 IS THE WHOLE REASON THIS FILE IS SHAPED THE WAY IT IS. `node look.mjs` drove /letter and
 * counted FOUR forms on it:
 *
 *   form.door-head  method="dialog"        the masthead drawer's closer
 *   form.find       action="/mornings"     the search box
 *   form.door-head  method="dialog"        the shell drawer's closer
 *   form.letter-form aria-label="The letter"  the one that subscribes
 *
 * and THREE submit-capable buttons, two of which have empty text. `document.querySelector("form")`
 * is the masthead drawer and `button[type=submit]` is its closer, so the obvious selectors close a
 * dialog and nothing errors. The letter form is addressed by its own class here.
 *
 * AND IT HAS NO `action` AND NO `method`. LetterForm.tsx is a client component that calls
 * preventDefault and posts JSON itself, because the route reads `request.json()` and a native form
 * post arrives form-encoded and comes back 400 "bad request" (the component's own header records
 * that being fixed on 2026-09-14). So this CLICKS the button and lets React run. `form.submit()`
 * would do a native GET to /letter, leave the page looking unchanged, and store nothing.
 *
 * THE ADDRESS IS TYPED WITH CAPITALS ON PURPOSE. Both the component and the route lowercase it, so
 * a stored row carrying the capitals was written past both of them.
 */
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3777";
const API = process.env.DESK_SUPABASE_URL || "http://127.0.0.1:54321";
const KEY = process.env.DESK_SERVICE_KEY || "";

/* Invented, on a .example domain that can never resolve. */
export const NEW_READER_AS_TYPED = "Wilhelmina.Carrow@Ashgrove-Press.example";
/* Her unsubscribe link is the one at the foot of the last letter she was sent. The token is the
 * fixture's, and it belongs to her STILLMORNINGS row; she holds a second subscription to soft
 * money journal under the same address, with a different token. */
export const LEAVING_READER_TOKEN = "00000000-0000-4000-8000-0000000fc001";

/** Fill the letter form on /letter and submit it once. */
async function subscribeFromThePage() {
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1400 });
    await page.goto(`${APP}/letter`, { waitUntil: "networkidle2", timeout: 60000 });
    await page.waitForSelector("form.letter-form input[type=email]", { timeout: 20000 });

    // Record where the page's own requests went, so the assertion is about the request that
    // happened rather than about the sentence that replaced the form.
    const posted = [];
    page.on("request", (r) => { if (r.method() === "POST") posted.push(r.url()); });

    await page.type("form.letter-form input[type=email]", NEW_READER_AS_TYPED);
    await page.evaluate(() => {
      document.querySelector("form.letter-form button[type=submit]").click();
    });

    // The form is REPLACED by `p.note[role=status]` only when the route answered ok. A failure
    // leaves the form standing with `p.note[role=alert]`, so this times out rather than passing.
    await page.waitForSelector("p.note[role=status]", { timeout: 20000 });
    const said = await page.$eval("p.note[role=status]", (el) => el.textContent.trim());
    const formGone = await page.evaluate(() => !document.querySelector("form.letter-form"));
    if (!formGone) throw new Error("the form is still on the page, so the route did not answer ok");

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

/** Open the unsubscribe link from the foot of a letter and confirm.
 *
 *  A GET NEVER WRITES, and that is deliberate in the route: corporate mail scanners prefetch every
 *  URL in an inbound message, so a route that removed a reader on GET would unsubscribe them on
 *  DELIVERY. The page it serves is one button and the POST behind it is the write. */
async function unsubscribeFromTheLink() {
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1000 });
    const link = `${APP}/api/subscribe/unsubscribe?token=${LEAVING_READER_TOKEN}`;
    await page.goto(link, { waitUntil: "networkidle2", timeout: 60000 });
    const before = await page.$eval("h1", (el) => el.textContent.trim());
    if (before !== "One more click") throw new Error(`the link served "${before}"`);

    await Promise.all([
      page.waitForNavigation({ waitUntil: "networkidle2", timeout: 30000 }),
      page.click('form[method="POST"] button[type="submit"]'),
    ]);
    const after = await page.$eval("h1", (el) => el.textContent.trim());
    if (after !== "You're off the list") throw new Error(`after confirming, the page said ${after}`);
    console.log(`confirmed through the link: ${before} -> ${after}`);
  } finally {
    await browser.close();
  }
}

/** Run the archive sync. The same entry point the estate's publication-sync job runs. */
function mirrorTheArchive() {
  return new Promise((resolve, reject) => {
    const child = spawn("node", ["publish.mjs", "still-mornings"], {
      cwd: path.join(HERE, "..", "engine", "social", "ugc"),
      env: { ...process.env, SUPABASE_URL: API, SUPABASE_SERVICE_ROLE_KEY: KEY },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    child.stdout.on("data", (b) => (out += b));
    child.stderr.on("data", (b) => (out += b));
    child.on("close", (code) => {
      process.stdout.write(out);
      code === 0 ? resolve() : reject(new Error(`publish.mjs exited ${code}`));
    });
  });
}

const TASKS = {
  "put-the-reader-on-the-letter": subscribeFromThePage,
  "take-the-reader-off-the-letter": unsubscribeFromTheLink,
  "mirror-the-archive-to-the-live-table": mirrorTheArchive,
};

const id = process.argv[2];
if (!TASKS[id]) {
  console.error(`unknown task ${id}. one of: ${Object.keys(TASKS).join(", ")}`);
  process.exit(2);
}
await TASKS[id]();
console.log(`rollout ok: ${id}`);
