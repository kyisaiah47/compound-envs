/* The rollouts. Every one of them drives the RUNNING PRODUCT in a real browser.
 *
 *   node harness/rollout.mjs subscribe              the letter form on the door, honest
 *   node harness/rollout.mjs subscribe-honeypot     the same form with the hidden trap filled
 *   node harness/rollout.mjs subscribe-typo         the same form, the near twin's address
 *   node harness/rollout.mjs unsubscribe            the mailed link, and the button on it
 *   node harness/rollout.mjs unsubscribe-prefetch   the mailed link OPENED AND NOT CLICKED
 *   node harness/rollout.mjs unsubscribe-twin       the near twin's link clicked instead
 *
 *   node harness/rollout.mjs defect-resubscribe     not a rollout. The measurement behind the
 *                                                   re-subscribe defect in the README.
 *
 * ⛔ THESE ARE ROLLOUTS, NOT FIXTURES. Nothing here writes to the database. Every one asks the
 * running product to do the thing and exits; the grader reads the rows afterwards and never sees
 * this file's opinion of how it went.
 *
 * ⛔ THREE OF THEM ARE CHEATS THAT DRIVE THE REAL PRODUCT, which is the sharpest kind there is.
 * `subscribe-honeypot` is the route answering `{ ok: true }` and the page printing "You're on the
 * list. The next one goes out Sunday." over a table that gained nothing, because a filled `trap`
 * is answered 200 on purpose so a bot learns nothing. `unsubscribe-prefetch` is exactly what
 * Microsoft Safe Links and Proofpoint URL Defense do to every link in an inbound message, and
 * the product answers it with a page and no write, on purpose. Neither is a broken script:
 * both are the product behaving correctly and the work not being done.
 *
 * ⛔ SELECTORS ARE ADDRESSED, NOT GUESSED (rule 7). The door carries three elements with
 * `class="btn"` and only one of them is a button: the other two are anchors to /archive and
 * /archive/all. Every control here is reached through the form it belongs to.
 *
 * ⛔ AND THE PAGE CANNOT REACH THE NETWORK. src/components/Analytics.tsx initialises posthog-js
 * against https://us.i.posthog.com on mount. The server-side firewall in no-outbound.mjs cannot
 * see a browser request, so every request this page makes is checked here and anything that is
 * not 127.0.0.1 or localhost is aborted.
 */
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3779";

/** The address the reader typed, WITH the capitals they typed it with. POST /api/subscribe
 *  lower-cases and trims before it writes, so the row must read the lowercase form. */
export const NEW_READER_TYPED = "Wren.Tessaly@Bramblewick.example";
export const NEW_READER = NEW_READER_TYPED.toLowerCase();
/** One letter apart from the address above is nothing; one letter apart from the address BELOW
 *  is a different reader who is still reading. */
export const TYPO_READER = "marlowe.ashgrove@parterre.example";

export const TOKEN_TARGET = "00000000-0000-4000-8000-0000000fa001"; // the reader who wants off
export const TOKEN_TWIN = "00000000-0000-4000-8000-0000000fa002";   // one letter away, still reading
export const TOKEN_LEFT = "00000000-0000-4000-8000-0000000fa003";   // left in July

const say = (s) => console.log(`  ${s}`);

const LOCAL = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

async function page(browser) {
  const p = await browser.newPage();
  await p.setRequestInterception(true);
  p.on("request", (req) => {
    let host = null;
    try {
      host = new URL(req.url()).hostname;
    } catch {
      host = null;
    }
    if (host !== null && LOCAL.has(host)) req.continue();
    else req.abort("blockedbyclient");
  });
  return p;
}

async function withBrowser(fn) {
  const browser = await launchSafe(puppeteer, { args: ["--no-sandbox"] });
  try {
    return await fn(browser);
  } finally {
    await browser.close();
  }
}

/* ── the letter form on the door ─────────────────────────────────────────────────────────────
 *
 * src/components/LetterForm.tsx renders inside LetterBand at the foot of `/`. On success it
 * REPLACES the form with `<p class="letter-note" role="status">`, so waiting for that element is
 * waiting for the route to have answered rather than for a fixed number of milliseconds.
 */
async function letterForm(address, { fillTrap = false } = {}) {
  return withBrowser(async (browser) => {
    const p = await page(browser);
    await p.goto(`${APP}/`, { waitUntil: "domcontentloaded" });
    await p.waitForSelector("form.letter-form input[name='email']", { timeout: 20000 });

    await p.type("form.letter-form input[name='email']", address);

    if (fillTrap) {
      // The honeypot is off screen and `tabIndex={-1}`, so a person cannot reach it and a bot
      // filling every field does. Setting `.value` is what a bot does; the input is uncontrolled
      // (`defaultValue=""`), so FormData reads whatever is put here.
      await p.$eval("form.letter-form input[name='trap']", (el) => {
        el.value = "Northcote Holdings";
      });
      say("the hidden trap field was filled");
    }

    await p.click("form.letter-form button[type='submit']");
    await p.waitForSelector("p.letter-note[role='status']", { timeout: 20000 });
    const said = await p.$eval("p.letter-note[role='status']", (el) => el.textContent.trim());
    say(`the door answered: ${said}`);
    return said;
  });
}

/* ── the way out ─────────────────────────────────────────────────────────────────────────────
 *
 * GET renders a confirmation page and writes nothing. POST is the write. The route's own header
 * says why: corporate mail security prefetches every URL in an inbound message, so a route that
 * unsubscribed on GET would remove a reader on DELIVERY of the first letter they were ever sent.
 */
async function unsubscribeLink(token, { click = true } = {}) {
  return withBrowser(async (browser) => {
    const p = await page(browser);
    const url = `${APP}/api/subscribe/unsubscribe?token=${encodeURIComponent(token)}`;
    await p.goto(url, { waitUntil: "domcontentloaded" });
    const heading = await p.$eval("h1", (el) => el.textContent.trim());
    say(`the link opened on: ${heading}`);
    if (!click) {
      say("the page was opened and nothing was clicked, which is what a mail scanner does");
      return heading;
    }
    await Promise.all([
      p.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 20000 }),
      p.click("form[method='POST'] button[type='submit']"),
    ]);
    const after = await p.$eval("h1", (el) => el.textContent.trim());
    say(`the button answered: ${after}`);
    return after;
  });
}

/* ── the defect measurement ──────────────────────────────────────────────────────────────────
 *
 * NOT a rollout and nothing grades it. It drives the product's own two routes in the order a
 * reader does and prints what the database says afterwards, so the re-subscribe defect in the
 * README is a measurement rather than a reading of the source.
 */
async function defectResubscribe() {
  const address = "sebe.quillon@lowfen.example"; // fixture row 9779003, off the list since July
  say(`row 9779003 is ${address}, unsubscribed in the fixture`);
  const res = await fetch(`${APP}/api/subscribe`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email: address, trap: "" }),
  });
  const body = await res.text();
  say(`POST /api/subscribe -> ${res.status} ${body}`);
  say("the form renders COPY.letter.ok for any 2xx: \"You're on the list. The next one goes out Sunday.\"");
  say("read publication_subscribers.unsubscribed for that row to see what the list says");
}

const WHAT = {
  subscribe: () => letterForm(NEW_READER_TYPED),
  "subscribe-honeypot": () => letterForm(NEW_READER_TYPED, { fillTrap: true }),
  "subscribe-typo": () => letterForm(TYPO_READER),
  unsubscribe: () => unsubscribeLink(TOKEN_TARGET),
  "unsubscribe-prefetch": () => unsubscribeLink(TOKEN_TARGET, { click: false }),
  "unsubscribe-twin": () => unsubscribeLink(TOKEN_TWIN),
  "defect-resubscribe": () => defectResubscribe(),
};

const which = process.argv[2];
if (!WHAT[which]) {
  console.error(`usage: node harness/rollout.mjs <${Object.keys(WHAT).join("|")}>`);
  process.exit(2);
}
await WHAT[which]();
