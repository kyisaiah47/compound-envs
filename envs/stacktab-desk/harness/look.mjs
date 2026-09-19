/* Rule 2, measured rather than reasoned about.
 *
 *   node look.mjs
 *
 * unemploy's `workspaceSlices()` returns hardcoded empty arrays for six of its seven collections
 * unless the account is the demo account, so rows written by a task never appear on screen and
 * the task cannot be a browser task. stacktab has no equivalent function to read, because it has
 * no accounts at all: no sign-in, no session, no demo flag, no account table, nothing in the tree
 * that branches on who is asking. Every visitor gets the same statically generated page.
 *
 * So this drives it instead and writes down what is actually on the page: how many email inputs
 * and submit buttons the landing carries, which form each one belongs to, and where each form
 * sends. That is what decided which tasks can be browser tasks and which cannot.
 */
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3318";

const browser = await launchSafe(puppeteer);
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1400 });
await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

const found = await page.evaluate(() => {
  const emails = [...document.querySelectorAll('input[type="email"]')];
  const buttons = [...document.querySelectorAll('button[type="submit"]')];
  return {
    emailInputs: emails.map((e) => ({ id: e.id, name: e.name, placeholder: e.placeholder })),
    submitButtons: buttons.map((b) => b.textContent.trim()),
    forms: [...document.querySelectorAll("form")].map((f) => ({
      className: f.className,
      firstEmailId: f.querySelector('input[type="email"]')?.id ?? null,
    })),
    priceWatchHeading: document.querySelector("#watch")?.textContent.trim() ?? null,
    serviceControl: !!document.querySelector('select[name="service"], input[name="service"]'),
  };
});

console.log(JSON.stringify(found, null, 2));
await page.screenshot({ path: "look-landing.png", fullPage: false });
await browser.close();
