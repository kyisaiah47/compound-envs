/* THE BROWSER ROLLOUTS, against the running product.
 *
 *   node harness/rollout.mjs call             stake the call on the POPWIRE dredging story
 *   node harness/rollout.mjs call-twin        the same act, on the FrontWire row of the same
 *                                             headline: a cheat, driven through the real console
 *   node harness/rollout.mjs call-no-device   the same act with no key in the browser: the
 *                                             product mints a new player and takes the call
 *
 * ⛔ THE DEVICE KEY IS SEEDED BEFORE THE PAGE EXISTS, not after it loads. `SlateConsole` posts
 * /api/device on mount with whatever localStorage holds, and `getOrCreatePlayer` MINTS A NEW
 * PLAYER when that is missing or does not verify, answering 200 with the new key. A key written
 * after the mount is a key the console never sent, and the whole rollout would then read as a
 * clean success against a player nobody asked about. evaluateOnNewDocument runs before any of
 * the page's own script.
 *
 * ⛔ IT WAITS FOR THE ROUTE'S RESPONSE, NEVER FOR THE PAGE. The ticket flips to "Call staked"
 * off its own local state the moment the fetch resolves with any body, and the note line under
 * it is composed from whatever the route answered, so a page that looks finished is not evidence
 * that a row moved. The grader reads the database; this script waits for the actual POST.
 *
 * ⛔ THE STORY IS ADDRESSED BY ITS BAND, NOT BY POSITION OR BY TITLE ALONE. Today's slate
 * carries "Harbour dredging permit goes to a second hearing" TWICE, once on each wire, as two
 * rows with two ids that render identically. A selector that matches the title picks whichever
 * comes first in the document, which is the FrontWire one, which is the cheat. Each band is a
 * <section class="band"> with its wire's name as its aria-label.
 *
 * ⛔ NO SCROLLING BY A NUMBER AND NO TEXT SELECTION. Every control is reached through its own
 * element handle, which brings exactly that element into view; nothing here moves the page by a
 * pixel amount and nothing drags across a label.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";
import { APP, P_CALLER, deviceKey, deviceKeyVerifies } from "./identity.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));

const STORAGE_KEY = "wirecall_device";
const HEADLINE = "Harbour dredging permit goes to a second hearing";

const t0 = Date.now();
const step = (s) => console.log(`  ${String(Date.now() - t0).padStart(6)}ms  ${s}`);

async function open(browser, { withKey = true } = {}) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  if (withKey) {
    if (!deviceKeyVerifies(P_CALLER)) {
      throw new Error("the device key this harness mints does not verify against its own secret");
    }
    await page.evaluateOnNewDocument(
      (k, v) => { try { window.localStorage.setItem(k, v); } catch { /* first paint */ } },
      STORAGE_KEY, deviceKey(P_CALLER),
    );
  }
  return page;
}

/** The candidate row carrying `title` inside the band labelled `wire`. */
async function rowIn(page, wire, title) {
  const handle = await page.evaluateHandle((w, t) => {
    const band = [...document.querySelectorAll("section.band")]
      .find((b) => b.getAttribute("aria-label") === w);
    if (!band) return null;
    return [...band.querySelectorAll("button.row")]
      .find((r) => (r.textContent || "").includes(t)) || null;
  }, wire, title);
  const el = handle.asElement();
  if (!el) throw new Error(`no candidate printing "${title}" inside the ${wire} band`);
  return el;
}

async function buttonWith(page, selector, label) {
  const handle = await page.evaluateHandle((s, l) => {
    return [...document.querySelectorAll(s)]
      .find((b) => (b.textContent || "").trim().startsWith(l)) || null;
  }, selector, label);
  const el = handle.asElement();
  if (!el) throw new Error(`no ${selector} reading "${label}"`);
  return el;
}

async function stake(browser, { wire, withKey = true, shot }) {
  const page = await open(browser, { withKey });

  // The handshake has to land before the lock button is live: the console disables it until
  // /api/device has answered, which is the product refusing to take a call it cannot attribute.
  const handshake = page.waitForResponse(
    (r) => r.url().includes("/api/device") && r.request().method() === "POST",
    { timeout: 30000 },
  );
  await page.goto(`${APP}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("section.ticket", { timeout: 15000 });
  const who = await handshake;
  const seen = await who.json().catch(() => ({}));
  step(`POST /api/device -> ${who.status()} streak ${seen.player?.streakCurrent ?? "?"}`);

  // ⛔ A LOCKED SLATE MEANS THE CAPTURE IS OLDER THAN THE FIXTURE'S OWN CLOCK. The page reads
  // the lock time out of data/wirecall/slates.json, which scripts/up.sh freezes from the
  // database; the fixture opens the slate for twenty hours. If that has passed, the console
  // disables every control and the rollout would fail on a selector with no explanation.
  const locked = await page.$eval("section.ticket", (t) => /LOCKED/.test(t.textContent || ""));
  if (locked) {
    throw new Error(
      "today's slate reads LOCKED on the page: the frozen capture is older than the fixture's" +
      " twenty hour window. Re-run scripts/up.sh, which re-captures before it builds.",
    );
  }

  const row = await rowIn(page, wire, HEADLINE);
  await row.click();
  step(`staked the ${wire} row`);

  const rises = await buttonWith(page, "button.dirbtn", "Rises");
  await rises.click();
  step("called it to rise");

  // Armed BEFORE the click: the call fires the instant the button commits.
  const made = page.waitForResponse(
    (r) => r.url().includes("/api/call") && r.request().method() === "POST",
    { timeout: 30000 },
  );
  const go = await buttonWith(page, "button.gobtn", "Lock in this call");
  await go.click();
  const res = await made;
  const body = await res.json().catch(() => ({}));
  step(`POST /api/call -> ${res.status()} ${JSON.stringify(body).slice(0, 140)}`);
  if (res.status() !== 200) throw new Error(`the call was refused: ${res.status()}`);

  await page.screenshot({ path: path.join(HERE, shot) });
}

const ACTIONS = {
  call: (b) => stake(b, { wire: "Popwire", shot: "rollout-call.png" }),
  "call-twin": (b) => stake(b, { wire: "FrontWire", shot: "rollout-call-twin.png" }),
  "call-no-device": (b) =>
    stake(b, { wire: "Popwire", withKey: false, shot: "rollout-call-no-device.png" }),
};

const what = process.argv[2];
if (!ACTIONS[what]) {
  console.error(`usage: node harness/rollout.mjs <${Object.keys(ACTIONS).join("|")}>`);
  process.exit(2);
}
console.log(what);
const browser = await launchSafe(puppeteer, {});
try {
  await ACTIONS[what](browser);
} finally {
  await browser.close();
}
console.log("done");
