/* The honest rollout for one browser task, against the running product.
 *
 *   node harness/rollout.mjs approve-the-ardenhall-coo
 *   node harness/rollout.mjs take-back-the-barrantes-write
 *
 * ⛔ RULE 7, AND THIS CONSOLE IS FULL OF IT. Every open row carries a button reading "Approve"
 * and every held lead carries one reading "Take it back", so `page.click("button.act-go")` hits
 * whichever row the DOM happens to put first. Nothing errors, the page reloads, and the wrong
 * lead is approved. So every control here is addressed through the ARTICLE whose `.row-name`
 * carries the person the task names, and the article is asserted to be exactly one before
 * anything is clicked.
 *
 * ⛔ AND THE ROW HAS TO BE OPENED FIRST. `.row-body` is rendered for every row but its controls
 * only become clickable when `article.row[data-open="1"]`, which the `.row-head` button toggles.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const APP = process.env.DESK_APP_URL || session.appUrl || "http://127.0.0.1:3753";

const TASK = process.argv[2];
const TASKS = {
  "approve-the-ardenhall-coo": { who: "Teodora Vance", control: "Approve" },
  "take-back-the-barrantes-write": { who: "Ines Barrantes", control: "Take it back" },
};
const spec = TASKS[TASK];
if (!spec) {
  console.error(`unknown task "${TASK}". Known: ${Object.keys(TASKS).join(", ")}`);
  process.exit(2);
}

const browser = await launchSafe(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1400 });
  await browser.setCookie(...session.cookies);
  await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

  /* The console renders the demo book to anybody without a session and it looks like a real book,
   * so "the page loaded" proves nothing. The tenant's own HubSpot label does. */
  const tenant = await page.evaluate(() => document.body.innerText.includes("Harlow Instruments"));
  if (!tenant) throw new Error("the console rendered the demo book: the session did not reach the server");

  /* ⛔ TOGGLE, NOT OPEN. `Console` opens the highest ranked waiting lead on mount
   * (`useState(openId ?? first)`), so the row a task names is sometimes ALREADY open and clicking
   * its head shuts it. The first cut of this file clicked unconditionally and then failed on
   * "the row did not open", which is the good outcome; the bad one is a control that is present
   * in the DOM either way and gets clicked through a closed row. Read the state, then act. */
  const opened = await page.evaluate((who) => {
    const rows = [...document.querySelectorAll("article.row")].filter((a) =>
      (a.querySelector(".row-name")?.innerText || "").includes(who),
    );
    if (rows.length !== 1) return { ok: false, found: rows.length };
    const wasOpen = rows[0].getAttribute("data-open") === "1";
    if (!wasOpen) rows[0].querySelector("button.row-head").click();
    return { ok: true, wasOpen };
  }, spec.who);
  if (!opened.ok) throw new Error(`expected exactly one row for "${spec.who}", the page has ${opened.found}`);
  if (opened.wasOpen) console.log(`${spec.who}'s row was already open (it is the top of the queue)`);
  await new Promise((r) => setTimeout(r, 400));

  const clicked = await page.evaluate(
    ({ who, control }) => {
      const row = [...document.querySelectorAll("article.row")].find((a) =>
        (a.querySelector(".row-name")?.innerText || "").includes(who),
      );
      if (!row) return { ok: false, why: "the row disappeared" };
      if (row.getAttribute("data-open") !== "1") return { ok: false, why: "the row did not open" };
      const button = [...row.querySelectorAll("button.act")].find((b) =>
        b.innerText.trim().toLowerCase().startsWith(control.toLowerCase()),
      );
      if (!button) {
        return {
          ok: false,
          why: `no "${control}" control inside that row. It offers: ${[...row.querySelectorAll("button.act")]
            .map((b) => JSON.stringify(b.innerText.trim()))
            .join(", ") || "(nothing)"}`,
        };
      }
      button.click();
      return { ok: true };
    },
    { who: spec.who, control: spec.control },
  );
  if (!clicked.ok) throw new Error(clicked.why);

  /* The route is what writes, and `act()` reloads the page on a 2xx and paints a notice on
   * anything else. Wait for whichever lands, then report the notice if there is one, because a
   * silent refusal is the failure this is most likely to hide. */
  await page
    .waitForNavigation({ waitUntil: "networkidle2", timeout: 15000 })
    .catch(() => {});
  await new Promise((r) => setTimeout(r, 600));
  const notice = await page.evaluate(() => {
    const el = document.querySelector(".notice, .act-note[data-notice]");
    return el ? el.innerText.trim() : null;
  });
  await page.screenshot({ path: path.join(HERE, `rollout-${TASK}.png`), fullPage: true });

  console.log(`clicked "${spec.control}" inside ${spec.who}'s row`);
  if (notice) console.log(`the console answered: ${notice}`);
} finally {
  await browser.close();
}
