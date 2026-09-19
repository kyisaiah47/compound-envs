/* THE THREE HONEST ROLLOUTS, against the running product on 3300.
 *
 *   node harness/rollout.mjs run-the-free-check          browser, the console on /
 *   node harness/rollout.mjs remove-the-delivered-file   the delete link from the buyer's email
 *   node harness/rollout.mjs hand-over-the-finished-reading   the poll the console makes
 *
 * ⛔ IT ASSERTS ON THE ROUTE'S RESPONSE, NEVER ON THE PAGE. The console re-renders pleasantly
 * whatever happened: submitting sets `busy` and starts a 2s poll, and it stays in that state
 * for as long as nobody answers, which is exactly what a failed insert also looks like. The
 * grader reads the database; this script waits for the actual HTTP response so a rollout that
 * never reached the route fails loudly here rather than silently scoring 0 later.
 *
 * ⛔ THE TEXTAREAS ARE FILLED THROUGH REACT'S OWN VALUE SETTER, NOT page.type(). Both panes are
 * controlled components: assigning `el.value` moves the DOM and never tells React, so the state
 * stays empty, the action button stays disabled and the click does nothing at all. The native
 * setter plus a bubbling `input` event is what React's synthetic onChange actually listens for.
 * page.type() would work and takes about 40 seconds for 1,516 characters; this is the same
 * result in 30ms, and the byte-for-byte fidelity is the point: the grader compares the stored
 * row against fixtures/documents.json exactly, so a dropped or re-wrapped character fails.
 *
 * ⛔ THE ACTION BUTTON IS ADDRESSED INSIDE THE FIELD (rule 7). `.act` is the house action class
 * and the page carries several: two of them are `<Link className="act" href="/tailored">` in
 * the right rail. `section.field button.act` is the only real submit on the page, and clicking
 * one of the links instead navigates away with nothing written and no error anywhere.
 *
 * ⛔ NO SCROLLING AND NO TEXT SELECTION (hard rules 19 and 6 on recordings, and the same reason
 * applies to a rollout: a beat that scrolls to something already in frame is a beat pointed at
 * nothing). At 1440x900 the whole field is above the fold, so there is nothing to travel to.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3300";

const DOCS = JSON.parse(
  fs.readFileSync(path.join(HERE, "..", "fixtures", "documents.json"), "utf8"),
);

/* The order the buyer wrote in about, and the token the delivery email carried. In production
 * ops/worker.mjs mints that token with crypto.randomUUID() and ops/mail/send_tailored.py puts
 * `/api/delete?order=<id>&token=<token>` in the mail; here both are the fixture's, so the
 * rollout holds exactly what the buyer holds and nothing more. It never reads the database. */
const TARGET_ORDER = "00000000-0000-4000-8000-0000000f7021";
const TARGET_TOKEN = "7f0a1c22-0000-4000-8000-0000000f7021";

/* The finished reading the console is polling for. */
const READY_MATCH = "00000000-0000-4000-8000-0000000f7012";

const t0 = Date.now();
const step = (s) => console.log(`  ${String(Date.now() - t0).padStart(6)}ms  ${s}`);

/** Set a controlled textarea the way React hears it. */
const REACT_SET = `(sel, value) => {
  const el = document.querySelector(sel);
  if (!el) throw new Error('no element for ' + sel);
  const proto = Object.getPrototypeOf(el);
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  return el.value.length;
}`;

async function runTheFreeCheck(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.goto(`${APP}/`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector('section.field textarea[aria-label="Job posting text"]', {
    timeout: 20000,
  });
  step("console on screen");

  const setter = await page.evaluateHandle(`(${REACT_SET})`);
  const nPosting = await page.evaluate(
    (fn, sel, v) => fn(sel, v),
    setter,
    'section.field textarea[aria-label="Job posting text"]',
    DOCS.posting,
  );
  const nResume = await page.evaluate(
    (fn, sel, v) => fn(sel, v),
    setter,
    'section.field textarea[aria-label="Resume text"]',
    DOCS.resume,
  );
  step(`both panes filled: posting ${nPosting} chars, resume ${nResume} chars`);

  // The button is disabled until BOTH documents clear 40 characters. If it is still disabled,
  // React never saw the input and clicking would be a no-op that leaves no trace anywhere.
  const disabled = await page.$eval("section.field button.act", (b) => b.disabled);
  if (disabled) throw new Error("the check button is still disabled: React never saw the input");

  // Armed BEFORE the click. The insert fires on the click and a listener attached afterwards
  // can miss the response entirely on a fast local stack.
  const started = page.waitForResponse(
    (r) => r.url().endsWith("/api/match") && r.request().method() === "POST",
    { timeout: 30000 },
  );
  await page.click("section.field button.act");
  const res = await started;
  const body = await res.json().catch(() => ({}));
  step(`POST /api/match -> ${res.status()} ${JSON.stringify(body)}`);
  if (res.status() !== 200) throw new Error(`the check refused: ${res.status()}`);
  if (!body.id) throw new Error("the route returned no match id");

  await page.screenshot({ path: path.join(HERE, "rollout-check.png") });
  step("screenshot rollout-check.png");
}

async function removeTheDeliveredFile() {
  /* redirect: manual so the 303 itself is the evidence. Following it lands on /deleted, which
   * renders the same shell for every outcome including `badtoken` and `failed`, so the page is
   * not the answer and the Location header is. */
  const url = `${APP}/api/delete?order=${TARGET_ORDER}&token=${TARGET_TOKEN}`;
  const res = await fetch(url, { redirect: "manual" });
  const where = res.headers.get("location") || "";
  step(`GET /api/delete -> ${res.status} ${where}`);
  if (res.status !== 303) throw new Error(`expected a 303 from the delete route, got ${res.status}`);
  if (!where.includes("state=deleted")) {
    throw new Error(`the route reported ${where}, not state=deleted`);
  }
}

async function handOverTheFinishedReading() {
  const res = await fetch(`${APP}/api/match/${READY_MATCH}`);
  const body = await res.json().catch(() => ({}));
  step(`GET /api/match/${READY_MATCH} -> ${res.status} status=${body.status}`);
  if (res.status !== 200) throw new Error(`the poll refused: ${res.status}`);
  if (body.status !== "done") throw new Error(`the reading came back ${body.status}, expected done`);
  if (!body.result || !Array.isArray(body.result.requirements)) {
    throw new Error("the poll returned no requirements; the client has nothing to render");
  }
}

const NEEDS_BROWSER = new Set(["run-the-free-check"]);
const ROLLOUTS = {
  "run-the-free-check": runTheFreeCheck,
  "remove-the-delivered-file": removeTheDeliveredFile,
  "hand-over-the-finished-reading": handOverTheFinishedReading,
};

const what = process.argv[2];
if (!ROLLOUTS[what]) {
  console.error(`usage: node harness/rollout.mjs <${Object.keys(ROLLOUTS).join("|")}>`);
  process.exit(2);
}

console.log(what);
let browser = null;
try {
  if (NEEDS_BROWSER.has(what)) browser = await launchSafe(puppeteer, { headless: true });
  await ROLLOUTS[what](browser);
  console.log("done");
} finally {
  if (browser) await browser.close();
}
