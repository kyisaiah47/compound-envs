/* Rule 2, measured rather than read. unemploy has a `workspaceSlices()` that hands a non-demo
 * account six empty arrays; still-mornings has no accounts, no sign-in and no session anywhere in
 * its tree, so there is no equivalent function to read. What there is instead is a question rule 7
 * asks of every page: which controls are actually on it, and can a selector name one of them
 * without ambiguity.
 *
 *   node look.mjs
 *
 * It drives the two surfaces a rollout touches and prints what is on them.
 */
import puppeteer from "puppeteer";
import { launchSafe } from "./safe-chrome.mjs";

const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3777";
const TOKEN = process.env.DESK_LOOK_TOKEN || "00000000-0000-4000-8000-0000000fc004";

const browser = await launchSafe(puppeteer);
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 1400 });

  await page.goto(`${APP}/letter`, { waitUntil: "networkidle2", timeout: 60000 });
  const letter = await page.evaluate(() => ({
    forms: [...document.querySelectorAll("form")].map((f) => ({
      cls: f.className || null,
      method: f.getAttribute("method"),
      action: f.getAttribute("action"),
      label: f.getAttribute("aria-label"),
    })),
    emailInputs: [...document.querySelectorAll('input[type="email"]')].map((i) => ({
      name: i.name, placeholder: i.placeholder, id: i.id || null,
    })),
    allInputs: [...document.querySelectorAll("input")].map((i) => `${i.type}[name=${i.name || "-"}]`),
    submits: [...document.querySelectorAll('button[type="submit"], button:not([type])')]
      .map((b) => b.textContent.trim()),
  }));
  console.log("/letter");
  console.log(JSON.stringify(letter, null, 2));

  await page.goto(`${APP}/api/subscribe/unsubscribe?token=${TOKEN}`, {
    waitUntil: "networkidle2", timeout: 60000,
  });
  const unsub = await page.evaluate(() => ({
    heading: document.querySelector("h1")?.textContent ?? null,
    forms: [...document.querySelectorAll("form")].map((f) => ({
      method: f.getAttribute("method"), action: f.getAttribute("action"),
    })),
    buttons: [...document.querySelectorAll("button")].map((b) => b.textContent.trim()),
    robots: document.querySelector('meta[name="robots"]')?.content ?? null,
  }));
  console.log("\n/api/subscribe/unsubscribe?token=<a real token>  (GET)");
  console.log(JSON.stringify(unsub, null, 2));
} finally {
  await browser.close();
}
