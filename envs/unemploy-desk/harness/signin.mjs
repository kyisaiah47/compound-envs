/* Sign in once and freeze the session, so an episode starts at the desk rather than at a login.
 *
 * ⛔ THE SIGN-IN IS REAL, NOT A FORGED COOKIE. The app signs in with a magic link
 * (`signInWithOtp`) under PKCE, so the code verifier lives in the browser that asked for the
 * link and only that browser can complete the exchange. Writing a cookie by hand means guessing
 * @supabase/ssr's storage key and its chunking, and a guess that is subtly wrong produces a page
 * that renders signed-out while every check here reports success. So this drives the real form,
 * reads the real mail out of the local Mailpit, follows the real callback, and copies out
 * whatever cookies the app actually set.
 *
 * Mailpit is the local Supabase stack's own mail sink on 54324. Nothing leaves the machine and
 * no mail client is involved.
 *
 *   node harness/signin.mjs            # writes harness/session.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3773";
const MAILPIT = process.env.DESK_MAILPIT_URL || "http://127.0.0.1:54324";
const EMAIL = process.env.DESK_EMAIL || "desk@brightlinefacilities.example";
const OUT = path.join(HERE, "session.json");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clearMailbox() {
  await fetch(`${MAILPIT}/api/v1/messages`, { method: "DELETE" }).catch(() => {});
}

/** The newest message to EMAIL, or null. Polled: the send is async on the app's side. */
async function latestMessageId() {
  const res = await fetch(`${MAILPIT}/api/v1/messages?limit=10`);
  const body = await res.json();
  const hit = (body.messages || []).find((m) =>
    (m.To || []).some((t) => (t.Address || "").toLowerCase() === EMAIL.toLowerCase()),
  );
  return hit ? hit.ID : null;
}

/** The sign-in URL out of the message body. Supabase sends the verify link on the auth host;
 *  under PKCE it redirects to the app's own /auth/callback with a code. */
async function signInLinkFrom(id) {
  const res = await fetch(`${MAILPIT}/api/v1/message/${id}`);
  const msg = await res.json();
  const body = `${msg.Text || ""}\n${msg.HTML || ""}`;
  const urls = body.match(/https?:\/\/[^\s"'<>]+/g) || [];
  const link = urls.find((u) => u.includes("/auth/v1/verify") || u.includes("token="));
  if (!link) throw new Error(`no sign-in link in message ${id}; urls=${JSON.stringify(urls)}`);
  return link.replace(/&amp;/g, "&");
}

async function main() {
  await clearMailbox();

  const browser = await launchSafe(puppeteer, { headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  try {
    page.on("console", (m) => {
      if (m.type() === "error") console.error(`  page console: ${m.text()}`);
    });
    page.on("pageerror", (e) => console.error(`  page error: ${e.message}`));
    page.on("requestfailed", (r) => console.error(`  request failed: ${r.url()}`));

    await page.goto(`${APP}/sign-in`, { waitUntil: "networkidle2", timeout: 60000 });
    await page.waitForSelector("#email", { timeout: 20000 });

    /* ⛔ `form button[type=submit]` IS AMBIGUOUS ON THIS PAGE and the first match is the wrong
     * form. /sign-in carries the auth form and a newsletter form, whose buttons read "Email me a
     * sign-in link" and "Email me when a state changes one". Clicking by that selector submits
     * the newsletter, the page does not error, and no sign-in mail is ever sent. The button is
     * addressed through the field it belongs to instead. */
    await page.click("#email", { clickCount: 3 });
    await page.type("#email", EMAIL);
    const typed = await page.$eval("#email", (el) => el.value);
    if (typed !== EMAIL) throw new Error(`the email field holds ${JSON.stringify(typed)}`);

    const otpCall = page.waitForResponse((r) => r.url().includes("/auth/v1/otp"), {
      timeout: 15000,
    });
    await page.$eval("#email", (el) => {
      const form = el.closest("form");
      if (!form) throw new Error("#email is not inside a form");
      form.querySelector('button[type="submit"]').click();
    });
    try {
      const r = await otpCall;
      console.log(`  otp request -> ${r.status()}`);
    } catch {
      const shot = path.join(HERE, "signin-debug.png");
      await page.screenshot({ path: shot });
      const state = await page.evaluate(() => ({
        buttons: [...document.querySelectorAll("form button")].map((b) => b.textContent.trim()),
        say: document.querySelector(".formsay")?.textContent?.trim() ?? null,
        emailValue: document.querySelector("#email")?.value ?? null,
      }));
      throw new Error(
        `the form never called /auth/v1/otp. page state ${JSON.stringify(state)}; shot at ${shot}`,
      );
    }

    let id = null;
    for (let i = 0; i < 40 && !id; i++) {
      await sleep(500);
      id = await latestMessageId();
    }
    if (!id) throw new Error("no sign-in mail arrived within 20s");

    const link = await signInLinkFrom(id);
    /* Same browser, so the PKCE verifier the form stored is the one the exchange reads. */
    await page.goto(link, { waitUntil: "networkidle2", timeout: 60000 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

    const cookies = await browser.cookies();
    const authCookies = cookies.filter((c) => c.name.startsWith("sb-"));
    if (!authCookies.length) {
      throw new Error("callback completed but no sb-* cookie was set: the session did not stick");
    }

    /* Proof the session is real on the SERVER, not just that a cookie exists. A signed-out
     * render of this app is a perfectly valid page, so "the page loaded" proves nothing. */
    const signedIn = await page.evaluate(() =>
      fetch("/dashboard/api/intake", { credentials: "include" })
        .then((r) => r.status)
        .catch(() => 0),
    );
    if (signedIn === 401) throw new Error("cookies were set but the server still reads signed-out");

    fs.writeFileSync(
      OUT,
      JSON.stringify({ email: EMAIL, capturedAt: new Date().toISOString(), cookies: authCookies }, null, 2),
    );
    console.log(`signed in as ${EMAIL}`);
    console.log(`intake probe returned ${signedIn}`);
    console.log(`${authCookies.length} auth cookie(s) -> ${path.relative(process.cwd(), OUT)}`);
    for (const c of authCookies) console.log(`  ${c.name} (${String(c.value).length} bytes)`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(String(err.message || err));
  process.exit(1);
});
