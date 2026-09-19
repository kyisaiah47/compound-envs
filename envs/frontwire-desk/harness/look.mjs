/* RULE 2: what does this product render for a REAL signed-in account, not its demo one.
 *
 *   node envs/frontwire-desk/harness/look.mjs
 *
 * The answer has to be MEASURED by driving the page, because reading the source and concluding
 * it looks fine is how a task gets written against rows that never appear on a screen.
 *
 * This script signs in as the fixture's own account through the product's own form at /sign-in,
 * then walks the routes a member would expect to find something on, and prints the page title,
 * the byte length and whether the address it signed in as appears anywhere in the rendered text.
 * It writes a screenshot per route beside itself.
 *
 * WHAT IT MEASURED ON 2026-09-19, against the build scripts/up.sh makes: signing in succeeds,
 * the app navigates to `/`, and every route renders exactly what it rendered signed out. The
 * account's address appears on no page. There is no account view, no members' archive, no plan
 * badge and no signed-in chrome anywhere in the product, which is what the sign-in page's own
 * dek says: "The wire, the archive and the daily email are free to everyone, signed in or not."
 *
 * So the browser can carry the three tasks whose controls exist (the contact form and the two
 * mail-action button pages) plus the signup, and the two webhooks are API tasks because the
 * product has no control for them anywhere. That is recorded on each task in results.json.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3309";
const EMAIL = process.env.DESK_EMAIL || "marisol.enriquez@calderastudio.example";
const PASSWORD = process.env.DESK_PASSWORD || "frontwire-desk-fixture-password";

const ROUTES = ["/", "/archive", "/upgrade", "/sources", "/author", "/contact"];

const browser = await launchSafe(puppeteer, { args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1280, height: 900 });

await page.goto(`${APP}/sign-in`, { waitUntil: "networkidle2" });

// ⛔ RULE 7, SELECTORS ARE AMBIGUOUS. This page carries the sign-in form AND the footer's
// subscribe form, and both of them have a `button[type=submit]`. Addressing the controls through
// the form that holds the password field is what makes this the sign-in and not the newsletter.
const form = await page.$("form:has(input[type=password])");
if (!form) throw new Error("no form with a password field on /sign-in");
await (await form.$('input[type="email"]')).type(EMAIL);
await (await form.$('input[type="password"]')).type(PASSWORD);
await Promise.all([
  page.waitForNavigation({ waitUntil: "networkidle2", timeout: 20000 }).catch(() => null),
  (await form.$('button[type="submit"]')).click(),
]);
await new Promise((r) => setTimeout(r, 1500));

const session = await page.evaluate(() => {
  const out = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.includes("auth-token")) out[k] = String(localStorage.getItem(k)).slice(0, 40);
  }
  return out;
});
console.log(`signed in as ${EMAIL}`);
console.log(`landed on ${page.url()}`);
console.log(`supabase session in localStorage: ${Object.keys(session).length ? "yes" : "NO"}`);
console.log("");

for (const route of ROUTES) {
  await page.goto(`${APP}${route}`, { waitUntil: "networkidle2" });
  const seen = await page.evaluate((email) => {
    const text = document.body.innerText;
    return {
      title: document.title,
      bytes: document.documentElement.outerHTML.length,
      namesTheAccount: text.toLowerCase().includes(email.toLowerCase()),
      forms: document.querySelectorAll("form").length,
      signOut: /sign out|log out|your account|my plan|my membership/i.test(text),
    };
  }, EMAIL);
  const file = path.join(HERE, `look${route.replace(/\//g, "-") || "-home"}.png`);
  await page.screenshot({ path: file });
  console.log(
    `${route.padEnd(10)} ${String(seen.bytes).padStart(7)}B  forms=${seen.forms}` +
      `  names the account: ${seen.namesTheAccount ? "YES" : "no"}` +
      `  account chrome: ${seen.signOut ? "maybe" : "no"}   ${seen.title}`,
  );
}

await browser.close();
console.log(`\nscreenshots in ${path.relative(process.cwd(), HERE)}`);
fs.accessSync(HERE);
