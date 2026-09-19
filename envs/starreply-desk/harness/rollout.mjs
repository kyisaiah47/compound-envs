/* The honest rollout for `approve-the-rewritten-reply`, driven through the real console.
 *
 * The 3 star review at the Fishtown Google listing is held because the drafted reply offers a
 * refund and the voice profile does not license a remedy. The operator opens the row, rewrites
 * the reply so it promises nothing, and approves the wording they read.
 *
 * ⛔ RULE 7, SELECTORS ARE AMBIGUOUS. Every row on this queue carries its own Approve, Edit first
 * and Kill it, so `button.cta` matches five controls on five different reviews and the first of
 * them is the 1 star legal one. Each control is addressed inside the `article.fx` whose text
 * carries the reviewer's name.
 *
 * ⛔ THE CONTROL IS "APPROVE THIS WORDING", NOT "APPROVE". The plain Approve stages the agent's
 * own draft and the route then receives no body, so `edited` stays false and the refund goes out.
 * The edit has to be open when the control is pressed.
 *
 *   node harness/rollout.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3752";
const REVIEWER = "Dermot Vasquez";

/** The rewrite. It answers the wait, it commits to nothing, and it carries neither a remedy nor
 *  an admission of fault, so `promisesAllowed` has nothing to match. */
const REWRITE =
  "Thank you Dermot. Fifty minutes past a booked time is not the standard we hold, and reception" +
  " should have told you where things stood while you waited. The practice manager has the" +
  " appointment log for that morning and is going through it. Nadia Oyelaran, practice manager";

const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

const browser = await launchSafe(puppeteer, { headless: true });
try {
  await browser.setCookie(...session.cookies);
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  page.on("pageerror", (e) => console.error(`  page error: ${e.message}`));

  await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForSelector("article.fx", { timeout: 20000 });

  /** Press the control whose text is `label`, inside the card for `REVIEWER`. */
  const pressInRow = async (label) => {
    const hit = await page.evaluate(
      (who, want) => {
        const card = [...document.querySelectorAll("article.fx")].find((a) =>
          (a.textContent || "").includes(who),
        );
        if (!card) return "no card";
        const btn = [...card.querySelectorAll("button")].find(
          (b) => (b.textContent || "").replace(/\s+/g, " ").trim() === want,
        );
        if (!btn) {
          return `no control ${JSON.stringify(want)}; card has ${JSON.stringify(
            [...card.querySelectorAll("button")].map((b) => (b.textContent || "").trim()),
          )}`;
        }
        btn.click();
        return "ok";
      },
      REVIEWER,
      label,
    );
    if (hit !== "ok") throw new Error(`${label}: ${hit}`);
  };

  // Open the row. The 1 star row is open by default, so this one has to be expanded first.
  await page.evaluate((who) => {
    const card = [...document.querySelectorAll("article.fx")].find((a) =>
      (a.textContent || "").includes(who),
    );
    if (!card) throw new Error("the review row is not on the page");
    if (card.dataset.open !== "true") card.querySelector("button.fxR").click();
  }, REVIEWER);
  await new Promise((r) => setTimeout(r, 400));

  await pressInRow("Edit first");
  await page.waitForSelector("article.fx textarea", { timeout: 10000 });

  await page.evaluate(
    (who, text) => {
      const card = [...document.querySelectorAll("article.fx")].find((a) =>
        (a.textContent || "").includes(who),
      );
      const ta = card.querySelector("textarea");
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        "value",
      ).set;
      setter.call(ta, text);
      ta.dispatchEvent(new Event("input", { bubbles: true }));
    },
    REVIEWER,
    REWRITE,
  );

  const call = page.waitForResponse(
    (r) => /\/api\/replies\/[^/]+\/approve$/.test(new URL(r.url()).pathname),
    { timeout: 20000 },
  );
  await pressInRow("Approve this wording");
  const res = await call;
  const json = await res.json().catch(() => ({}));
  console.log(`  approve -> ${res.status()} ${JSON.stringify(json)}`);
  if (res.status() !== 200) throw new Error(`the approve route answered ${res.status()}`);

  await new Promise((r) => setTimeout(r, 800));
  const shot = path.join(HERE, "rollout-end.png");
  await page.screenshot({ path: shot });
  console.log(`shot -> ${path.relative(process.cwd(), shot)}`);
} finally {
  if (!process.argv.includes("--keep")) await browser.close();
  else await browser.close();
}
