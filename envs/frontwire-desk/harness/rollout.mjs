/* Drive the four browser-carryable tasks in a real Chrome, as a reader would.
 *
 *   node envs/frontwire-desk/harness/rollout.mjs            # all four
 *   node envs/frontwire-desk/harness/rollout.mjs letter     # one
 *
 * The graders are proven in adversarial/prove_graders.py, which drives the same routes over
 * HTTP. This exists for the other half: it shows that a person clicking the product's own
 * controls reaches those routes at all, which is the thing reading the source cannot tell you.
 *
 * ⛔ IT DOES NOT RESEED. Run `./scripts/up.sh` (or re-apply sql/02-seed.sql) first, and run one
 * task at a time if you want a clean starting state for each.
 *
 * ⛔ IT NEVER TOUCHES /upgrade. Its two buttons POST to /api/checkout, which on a deployment
 * carrying a real key opens a LIVE Stripe Checkout Session. This environment builds with a
 * placeholder key so the route answers 500 rather than reaching Stripe, and the rule stands
 * anyway: nothing here clicks a control whose job is to spend money.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3309";

const TOKEN_PRIYA = "f4510001-0000-4000-8000-000000000001";
const TOKEN_DEV = "f4510003-0000-4000-8000-000000000003";
const LETTER = {
  name: "August Pereira",
  email: "august.pereira@tidewaterreview.example",
  subject: "Wrong outlet on the Kermadec item",
  message:
    "The M 6.1 Kermadec Islands item credits the USGS but the link goes to the NWS alert. " +
    "Could you check /news/m6-1-earthquake-kermadec-islands-region?",
};
const SIGNUP = {
  email: "renata.villalobos@solsticepress.example",
  password: "frontwire-desk-fixture-password",
};

const only = process.argv[2] || null;
const browser = await launchSafe(puppeteer, { args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

const shot = (name) => page.screenshot({ path: path.join(HERE, `rollout-${name}.png`) });
const say = (line) => console.log(`  ${line}`);

/** The mail-action pages are hand-written HTML on the API route, not a React page: one form,
 *  one button, no client bundle. A GET renders the button and only the POST writes. */
async function pressTheButtonOnTheMailPage(url, label) {
  await page.goto(url, { waitUntil: "networkidle2" });
  const heading = await page.$eval("h1", (h) => h.textContent.trim());
  say(`GET rendered "${heading}" with ${await page.$$eval("form", (f) => f.length)} form`);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle2", timeout: 20000 }),
    page.click('form button[type="submit"]'),
  ]);
  const after = await page.$eval("h1", (h) => h.textContent.trim());
  say(`POST answered "${after}"`);
  await shot(label);
}

if (!only || only === "confirm") {
  console.log("\nconfirm-the-subscription  (the button in the confirmation email)");
  await pressTheButtonOnTheMailPage(
    `${APP}/api/subscribe/confirm?token=${TOKEN_PRIYA}`, "confirm",
  );
}

if (!only || only === "unsubscribe") {
  console.log("\ntake-the-reader-off-the-list  (the one-click link at the foot of the issue)");
  await pressTheButtonOnTheMailPage(
    `${APP}/api/subscribe/unsubscribe?token=${TOKEN_DEV}`, "unsubscribe",
  );
}

if (!only || only === "letter") {
  console.log("\nlog-the-letter-to-the-desk  (the form at /contact)");
  await page.goto(`${APP}/contact`, { waitUntil: "networkidle2" });
  // ⛔ RULE 7, SELECTORS ARE AMBIGUOUS, AND THIS PAGE IS THE LIVE PROOF OF IT. /contact renders
  // TWO forms: the contact form and the footer's subscribe form, each with its own
  // `button[type=submit]` and its own `input[name=email]`. Measured on the running app: two.
  // The obvious selector hits the newsletter, the letter is never filed, and nothing errors.
  const form = await page.$("form:has(textarea[name=message])");
  if (!form) throw new Error("no form with a message textarea on /contact");
  say(`/contact carries ${await page.$$eval("form", (f) => f.length)} forms; using the one with the textarea`);
  for (const [field, value] of Object.entries(LETTER)) {
    await (await form.$(`[name="${field}"]`)).type(value);
  }
  await (await form.$('button[type="submit"]')).click();
  await page.waitForFunction(
    () => /Message sent/.test(document.querySelector("form:has(textarea[name=message]) button").textContent),
    { timeout: 20000 },
  );
  say(`the button reads "${await form.$eval("button", (b) => b.textContent.trim())}"`);
  await shot("letter");
}

if (!only || only === "signup") {
  console.log("\nopen-the-account-that-already-paid  (the form at /sign-up)");
  await page.goto(`${APP}/sign-up`, { waitUntil: "networkidle2" });
  const form = await page.$("form:has(input[type=password])");
  if (!form) throw new Error("no form with a password field on /sign-up");
  await (await form.$('input[type="email"]')).type(SIGNUP.email);
  await (await form.$('input[type="password"]')).type(SIGNUP.password);
  await (await form.$('button[type="submit"]')).click();
  // SignInForm's sign-up branch stays on the page and prints what Supabase answered. Empty text
  // and a re-enabled button is the success shape on a stack with confirmations off.
  await page.waitForFunction(
    () => !document.querySelector("form:has(input[type=password]) button").disabled,
    { timeout: 20000 },
  );
  const said = await form.$$eval("p", (ps) => ps.map((p) => p.textContent.trim()).filter(Boolean));
  say(`the form says: ${JSON.stringify(said)}`);
  await shot("signup");
}

await browser.close();
console.log(`\nscreenshots in ${path.relative(process.cwd(), HERE)}`);
