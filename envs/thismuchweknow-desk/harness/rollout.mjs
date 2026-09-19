/* The honest rollout for each task. It drives the REAL running product, never the database.
 *
 *   node rollout.mjs <task-id>
 *
 * THE LETTER FORM IS ON ONE ROUTE AND IT IS NOT THE LANDING (rule 2, measured by harness/look.mjs
 * at 1440). `/about`, the manifesto, linked in the nav as "The method". The four sibling
 * publications put the same component at the foot of every page, so a rollout copied from them
 * drives `/`, finds no `input[type=email]` and times out.
 *
 * THE PAGE'S FIRST `button[type=submit]` IS NOT THE LETTER'S (rule 7). It belongs to
 * `form.door-head`, the left rail's dialog close button, and clicking it closes a drawer while
 * nothing errors and no address is stored. So this finds `form.letter-form` by its own class,
 * clicks the button inside THAT form, and then asserts from inside the page that exactly one POST
 * was made and that it went to /api/subscribe on this origin.
 *
 * AND THE CONFIRMATION LINE PROVES NOTHING BY ITS PRESENCE. LetterForm keeps the form standing and
 * prints `COPY.letter.ok` or `COPY.letter.fail` into the SAME `span.hits`, so the rollout compares
 * the text. Both literals below are src/copy.ts's own.
 *
 * ⛔ IT DRIVES THE SAME FORM FOR BOTH TASKS, BECAUSE THE PRODUCT HAS ONE WRITE. What differs is
 * the address and the state the fixture left that address in: a stranger, and a reader whose row
 * is already there with `unsubscribed = true`.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3330";

/* src/copy.ts, `letter`. `ok` and `fail` land in the same element, so the text is the only thing
 * that separates a stored address from a refused one. */
const OK_LINE = "You're on the list. The first one hasn't gone out yet.";
const FAIL_LINE = "That didn't go through. Try again in a minute.";

/* The people in the fixture's prompts. Every address is invented and every domain is `.example`.
 * The first is typed with capitals and surrounding space on purpose: the route trims and
 * lowercases, so a row carrying the typed form was written past it. */
export const NEW_READER_AS_TYPED = "  Marguerite.Ashcombe@Pellwood-Signal.example ";
export const RETURNING_READER = "delia.marchetti@stourbridge-ferry.example";

/** Type one address into the letter form on /about and submit it once. */
async function submitTheLetterForm(address) {
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1200 });
    await page.goto(`${APP}/about`, { waitUntil: "networkidle2", timeout: 60000 });
    await page.waitForSelector("form.letter-form input[name=email]", { timeout: 20000 });

    // Record where the page's own requests went, so the assertion is about the request that
    // happened rather than about the line the form printed afterwards.
    const posted = [];
    page.on("request", (r) => {
      if (r.method() === "POST") posted.push(r.url());
    });

    await page.type("form.letter-form input[name=email]", address);
    await page.evaluate(() => {
      const form = document.querySelector("form.letter-form");
      form.querySelector('button[type="submit"]').click();
    });

    await page.waitForSelector("form.letter-form span.hits", { timeout: 20000 });
    const said = await page.$eval("form.letter-form span.hits", (el) => el.textContent.trim());
    if (said === FAIL_LINE) {
      throw new Error("the form printed copy.ts's `fail` line, so the route refused the address");
    }
    if (said !== OK_LINE) {
      throw new Error(`the form printed ${JSON.stringify(said)}, which is neither ok nor fail`);
    }

    const foreign = posted.filter((u) => !u.startsWith(APP));
    if (foreign.length) throw new Error(`the page posted off-origin: ${foreign.join(", ")}`);
    const ours = posted.filter((u) => u.endsWith("/api/subscribe"));
    if (ours.length !== 1) {
      throw new Error(
        `expected one POST to /api/subscribe, saw ${posted.length}: ${posted.join(", ")}`,
      );
    }
    console.log(`submitted once, ${ours[0]}`);
    console.log(`the page said: ${said}`);
  } finally {
    await browser.close();
  }
}

const TASKS = {
  "subscribe-from-the-letter-form": () => submitTheLetterForm(NEW_READER_AS_TYPED),
  "put-the-returning-reader-back": () => submitTheLetterForm(RETURNING_READER),
};

const id = process.argv[2];
if (!TASKS[id]) {
  console.error(`usage: node rollout.mjs <${Object.keys(TASKS).join("|")}>`);
  process.exit(2);
}
await TASKS[id]();
