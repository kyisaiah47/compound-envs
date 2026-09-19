/* Open the console as the fixture's REAL signed-in account and report what each surface renders,
 * then press the one control the console has and record what the product does with it.
 *
 * ⛔ THIS IS RULE 2, AND IT IS A MEASUREMENT, NOT A READ OF THE SOURCE. Several products in this
 * estate return hardcoded empty collections, or a demo book, for any account that is not their
 * demo account, and the code that does it reads as perfectly ordinary. A task whose rows never
 * reach the screen cannot be a browser task, and the only way to know is to drive the page.
 *
 * ⛔ THE FIVE ROUTES ARE READ OFF `src/app/dashboard/nav-map.ts`, NEVER GUESSED. `VIEW_TO_ROUTE`
 * maps every `?view=` the live product publishes onto one of five real paths, and
 * `routeForView()` sends anything it does not know to `/`. Walking invented view names would
 * photograph the queue five times and report it as five surfaces.
 *
 *   node harness/look.mjs            # screenshots + a per-surface count + the control probe
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const APP = process.env.DESK_APP_URL || session.appUrl || "http://127.0.0.1:3751";

const SURFACES = [
  ["queue", "/"],
  ["threads", "/threads"],
  ["record", "/record"],
  ["rails", "/rails"],
  ["settings", "/settings"],
];

/* Customers this fixture owns and the generated demo book (Northwind's conversations) cannot
 * contain. If one of these is on the page, the page is this account's own book. */
const OURS = [
  "Marguerite Vane",
  "Martin Vane",
  "Pernilla Okonjo",
  "Delphine Mazzocchi",
  "Harrowgate Tools",
];
/* The demo book's own mailbox. If THIS is on the page while a session is set, the console fell
 * through to the demo tenant and nothing below means what it says. */
const THEIRS = "support@northwind.example";

const browser = await launchSafe(puppeteer, { headless: true });
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1200 });
  await browser.setCookie(...session.cookies);

  for (const [name, route] of SURFACES) {
    await page.goto(`${APP}${route}`, { waitUntil: "networkidle2", timeout: 60000 });
    await new Promise((r) => setTimeout(r, 600));
    const seen = await page.evaluate((ours) => {
      const text = document.body.innerText;
      return {
        url: location.href,
        rows: document.querySelectorAll("article.fx").length,
        acts: [...document.querySelectorAll(".acts button")].map((b) => b.innerText.trim().replace(/\s+/g, " ")),
        ours: ours.filter((o) => text.includes(o)),
        text: text.replace(/\s+/g, " ").slice(0, 420),
      };
    }, OURS);
    const demo = await page.evaluate((theirs) => document.body.innerText.includes(theirs), THEIRS);
    console.log(`\n${name}  ${seen.url}`);
    console.log(`  queue cards: ${seen.rows}`);
    if (seen.acts.length) console.log(`  controls: ${JSON.stringify(seen.acts.slice(0, 6))}`);
    console.log(`  this fixture's own rows on the page: ${JSON.stringify(seen.ours)}`);
    console.log(`  the demo book's mailbox on the page: ${demo}`);
    console.log(`  ${seen.text}`);
    await page.screenshot({ path: path.join(HERE, `look-${name}.png`), fullPage: false });
  }

  /* ⛔ THE CONTROL PROBE. `components/Queue.tsx act()` is the only client-side call anywhere in
   * this repo: a single `fetch` to `/api/queue/<row.key>`. What it sends is measured here rather
   * than read off the source, because the whole question is which identifier ends up in the URL
   * and what the route answers when it arrives. */
  await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });
  await new Promise((r) => setTimeout(r, 600));
  const calls = [];
  page.on("request", (r) => {
    if (r.url().includes("/api/queue/")) calls.push({ url: r.url(), method: r.method() });
  });
  page.on("response", async (r) => {
    if (!r.url().includes("/api/queue/")) return;
    let body = "";
    try {
      body = (await r.text()).slice(0, 200);
    } catch {
      /* a response body that is already gone tells us nothing and must not throw here */
    }
    const hit = calls.find((c) => c.url === r.url());
    if (hit) {
      hit.status = r.status();
      hit.body = body;
    }
  });

  const pressed = await page.evaluate(() => {
    const card = [...document.querySelectorAll("article.fx")].find(
      (a) => a.getAttribute("data-st") === "waiting",
    );
    if (!card) return null;
    const head = card.querySelector(".fx-h")?.innerText?.trim() ?? "";
    const who = card.querySelector(".fx-from")?.innerText?.trim() ?? "";
    const open = card.getAttribute("data-open") === "true";
    if (!open) card.querySelector("button.fx-r")?.click();
    return { head, who };
  });
  await new Promise((r) => setTimeout(r, 500));
  const clicked = await page.evaluate(() => {
    const card = [...document.querySelectorAll("article.fx")].find(
      (a) => a.getAttribute("data-st") === "waiting",
    );
    const btn = [...(card?.querySelectorAll(".acts button") ?? [])].find((b) =>
      b.innerText.toLowerCase().includes("approve"),
    );
    if (!btn) return false;
    btn.click();
    return true;
  });
  await new Promise((r) => setTimeout(r, 1500));
  const toast = await page.evaluate(() => {
    const el = document.querySelector(".toast, [class*='toast']");
    return el ? el.innerText.trim() : null;
  });

  console.log(`\nthe Approve control, pressed on ${JSON.stringify(pressed)}`);
  console.log(`  clicked: ${clicked}`);
  for (const c of calls) {
    console.log(`  ${c.method} ${c.url.replace(APP, "")} -> ${c.status} ${c.body}`);
  }
  console.log(`  what the console told the operator: ${JSON.stringify(toast)}`);
  await page.screenshot({ path: path.join(HERE, "look-approve-pressed.png"), fullPage: false });
} finally {
  await browser.close();
}
