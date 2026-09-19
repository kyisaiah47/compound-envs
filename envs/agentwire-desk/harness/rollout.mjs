/* Drive the three browser-carryable tasks in a real Chrome, as a reader would.
 *
 *   node envs/agentwire-desk/harness/rollout.mjs              # all three
 *   node envs/agentwire-desk/harness/rollout.mjs subscribe    # one
 *
 * The graders are proven in adversarial/prove_graders.py, which drives the same routes over
 * HTTP. This exists for the other half: it shows that a person operating Agentwire's own
 * controls reaches those routes at all, which is the thing reading the source cannot tell you.
 *
 * ⛔ IT DOES NOT RESEED. Run `./scripts/up.sh` (or re-apply sql/02-seed.sql) first, and run one
 * task at a time if you want a clean starting state for each.
 *
 * ⛔ THE FOURTH TASK IS NOT HERE, AND THAT IS NOT AN OMISSION. The mirror is
 * `node scripts/mirror-posts.mjs`, a script the lane's run script calls after a posting tick.
 * There is no control for it on any page, in the same way there is no page anywhere in this
 * product that can create, edit or remove an entry: the site is a read of what the accounts
 * already posted. prove_graders.py runs the real script for that one.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3741";

const TOKEN_PENDING = "00000000-0000-4000-8000-0000000f9701";   // wren.holloway
const TOKEN_READER = "00000000-0000-4000-8000-0000000f9703";    // mirren.vasquez
const NEW_READER = "teodora.brask@awdesk.invalid";

const only = process.argv[2] || null;
const browser = await launchSafe(puppeteer, { args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

const shot = (name) => page.screenshot({ path: path.join(HERE, `rollout-${name}.png`) });
const say = (line) => console.log(`  ${line}`);

/** Both mail-action pages are hand-written HTML on the API route, not a React page: one form,
 *  one button, no client bundle. A GET renders the button and only the POST writes. */
async function pressTheButtonOnTheMailPage(url, label) {
  await page.goto(url, { waitUntil: "networkidle2" });
  const heading = await page.$eval("h1", (h) => h.textContent.trim());
  const forms = await page.$$eval("form", (f) => f.length);
  say(`GET rendered "${heading}" with ${forms} form and wrote nothing`);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle2", timeout: 20000 }),
    page.click('form button[type="submit"]'),
  ]);
  say(`POST answered "${await page.$eval("h1", (h) => h.textContent.trim())}"`);
  await shot(label);
}

if (!only || only === "subscribe") {
  console.log("\nput-the-reader-on-the-list  (the footer form, on every page)");
  await page.goto(`${APP}/`, { waitUntil: "networkidle2" });

  // ⛔ RULE 7 ON THIS PRODUCT, AND IT IS NOT THE USUAL SHAPE. There is exactly ONE form on the
  // whole site, so "which form" is never the question here. The question is WHICH INPUT: the
  // footer form carries TWO, and the second is a HONEYPOT, `input[name=website]`, parked at
  // `transform: scale(0)`. Subscribe.tsx checks it FIRST and, if anything is in it, sets the
  // component straight to its success state and NEVER POSTS. So a rollout that fills every
  // input on the form gets "Check your inbox and confirm", a green screenshot, and no row,
  // with nothing erroring anywhere. Address the field that is actually the address.
  const shape = await page.$$eval("form input", (els) =>
    els.map((e) => `${e.getAttribute("name")}:${e.type}`),
  );
  say(`the footer form carries inputs ${JSON.stringify(shape)}; the honeypot is never touched`);
  await page.type('form input[name="email"]', NEW_READER);
  await page.click('form button[type="submit"]');
  await page.waitForFunction(
    () => {
      const el = document.querySelector('[role="status"]');
      return el && /Check your inbox/i.test(el.textContent || "");
    },
    { timeout: 20000 },
  );
  say(`the form answered "${await page.$eval('[role="status"]', (e) => e.textContent.trim())}"`);
  await shot("subscribe");
}

if (!only || only === "confirm") {
  console.log("\nconfirm-the-subscription  (the button in the confirmation email)");
  await pressTheButtonOnTheMailPage(
    `${APP}/api/subscribe/confirm?token=${TOKEN_PENDING}`,
    "confirm",
  );
}

if (!only || only === "unsubscribe") {
  console.log("\ntake-the-reader-off-the-list  (the one-click link at the foot of the issue)");
  await pressTheButtonOnTheMailPage(
    `${APP}/api/subscribe/unsubscribe?token=${TOKEN_READER}`,
    "unsubscribe",
  );
}

await browser.close();
console.log("\ndone. The rows are what decide the score; see adversarial/prove_graders.py.");
