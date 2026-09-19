/* THE TWO BROWSER ROLLOUTS, against the running product.
 *
 *   node harness/rollout.mjs tear       tear the sealed pack on /rip
 *   node harness/rollout.mjs trade-in   destroy the two Ash Blobs on /trade-in
 *
 * ⛔ IT ASSERTS ON THE ROUTE'S RESPONSE, NEVER ON THE PAGE. Both surfaces re-render pleasantly
 * whatever happened: the rip stage animates the same way before the mint returns, and the
 * trade-in tray prints a toast composed from whatever the route answered. A page that looks
 * finished is not evidence that a row moved, which is why the grader reads the database and this
 * script waits for the actual response.
 *
 * ⛔ NO SCROLLING AND NO TEXT SELECTION. Both controls are in frame the moment the page renders
 * at 1440x900, so there is nothing to travel to, and a click that lands on a card is a click on a
 * button rather than a drag across its label.
 *
 * ⛔ THE CARDS ARE ADDRESSED BY THEIR PRINTED MINT NUMBER, NOT BY POSITION. The collection is
 * ordered by rating descending and this fixture deliberately holds TWO cards rated 57, so the
 * order between them is whatever Postgres returns and an nth-child selector picks a different
 * card on a different day. The mint number is on the face of each card and is unique.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";
import { APP, BUYER_ONE, buyerCookie } from "./identity.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
void HERE;

const ORDER_SEALED = "00000000-0000-4000-8000-0000000fa004";
/** fenwick.example pulls 8 and 2: both Ash Blobs, both rated 57, both Tier I, from two
 *  different packs. Their mint numbers are the only thing on screen that tells them apart. */
const TARGET_MINTS = ["571/999", "615/999"];

const t0 = Date.now();
const step = (s) => console.log(`  ${String(Date.now() - t0).padStart(6)}ms  ${s}`);

async function open(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await page.setCookie({
    name: "outrip_buyer",
    value: buyerCookie(BUYER_ONE),
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
  });
  return page;
}

async function tear(browser) {
  const page = await open(browser);
  await page.goto(`${APP}/rip?order=${ORDER_SEALED}`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".rp-pack", { timeout: 15000 });
  step("sealed pack on screen");

  // Armed BEFORE the click: the tear fires the mint the instant the strip commits, and a
  // listener attached afterwards can miss it.
  const minted = page.waitForResponse(
    (r) => r.url().includes("/api/rip/open") && r.request().method() === "POST",
    { timeout: 30000 },
  );
  await page.click(".rp-pack");
  step("wrapper torn");

  const res = await minted;
  const body = await res.json().catch(() => ({}));
  step(`POST /api/rip/open -> ${res.status()}`);
  if (res.status() !== 200) throw new Error(`the mint refused: ${res.status()}`);
  if (!Array.isArray(body.cards) || body.cards.length !== 5) {
    throw new Error(`the mint returned ${body.cards?.length ?? "no"} cards, expected 5`);
  }
  step(`cards: ${body.cards.map((c) => c.rating).join(", ")}`);
  await page.screenshot({ path: path.join(HERE, "rollout-tear.png") });
}

async function tradeIn(browser) {
  const page = await open(browser);
  await page.goto(`${APP}/trade-in`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector(".ti-pick", { timeout: 15000 });
  step("collection on screen");

  for (const mint of TARGET_MINTS) {
    const handle = await page.evaluateHandle((m) => {
      const cells = [...document.querySelectorAll("button.ti-pick")];
      return cells.find((c) => (c.textContent || "").includes(m)) || null;
    }, mint);
    const el = handle.asElement();
    if (!el) throw new Error(`no card on screen printing mint ${mint}`);
    await el.click();
    step(`selected ${mint}`);
  }

  const selected = await page.$$eval("button.ti-pick[aria-pressed='true']", (n) => n.length);
  if (selected !== 2) throw new Error(`${selected} cards selected, expected 2`);

  const done = page.waitForResponse(
    (r) => r.url().includes("/api/trade-in") && r.request().method() === "POST",
    { timeout: 30000 },
  );
  await page.click(".ti-btn");
  const res = await done;
  const body = await res.json().catch(() => ({}));
  step(`POST /api/trade-in -> ${res.status()} ${JSON.stringify(body)}`);
  if (res.status() !== 200) throw new Error(`the trade-in refused: ${res.status()}`);
  await page.screenshot({ path: path.join(HERE, "rollout-tradein.png") });
}

const ROLLOUTS = { tear, "trade-in": tradeIn };
const what = process.argv[2];
if (!ROLLOUTS[what]) {
  console.error(`usage: node harness/rollout.mjs <${Object.keys(ROLLOUTS).join("|")}>`);
  process.exit(2);
}

console.log(what);
const browser = await launchSafe(puppeteer, { headless: true });
try {
  await ROLLOUTS[what](browser);
  console.log("done");
} finally {
  await browser.close();
}
