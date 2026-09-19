/* Sign in once and freeze the session, so an episode starts on the queue rather than at a gate.
 *
 * ⛔ THE SIGN-IN IS REAL, NOT A FORGED COOKIE. MatchRail has no password. `_console/SignIn.tsx`
 * says so on the page ("There is no password on MatchRail and no signup form") and offers exactly
 * one control, `signInWithOtp`. OTP runs under PKCE, so the code verifier lives in the browser
 * that asked for the link and only that browser can complete the exchange. Writing a cookie by
 * hand means guessing @supabase/ssr's storage key and its chunking, and a guess that is subtly
 * wrong renders a signed-out page while every check here reports success. So this drives the real
 * form, reads the real mail out of the local Mailpit, follows the real callback, and copies out
 * whatever cookies the app actually set.
 *
 * ⛔ THE GATE IS A QUERY PARAMETER, NOT A ROUTE. `/` IS the console. The form only exists once
 * `?signin=1` is read, and there is no /sign-in page on this tree.
 *
 * ⛔ RULE 7, SELECTORS ARE AMBIGUOUS. This harness never uses a bare `input[type=email]` or
 * `button[type=submit]`: it counts how many of each the page carries, prints the count, and
 * addresses the control through `form.mr-signin`, the form that owns it. MatchRail ships a
 * `ListCapture` mailing-list form with an identical field, and a bare selector that reached it
 * would subscribe an address and report a sign-in that never happened.
 *
 *   node harness/signin.mjs            # writes harness/session.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3755";
const MAILPIT = process.env.DESK_MAILPIT_URL || "http://127.0.0.1:54324";
const EMAIL = process.env.DESK_EMAIL || "desk@northarbormill.example";
const OUT = path.join(HERE, "session.json");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clearMailbox() {
  await fetch(`${MAILPIT}/api/v1/messages`, { method: "DELETE" }).catch(() => {});
}

async function latestMessageId() {
  const res = await fetch(`${MAILPIT}/api/v1/messages?limit=10`);
  const body = await res.json();
  const hit = (body.messages || []).find((m) =>
    (m.To || []).some((t) => (t.Address || "").toLowerCase() === EMAIL.toLowerCase()),
  );
  return hit ? hit.ID : null;
}

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
    page.on("pageerror", (e) => console.error(`  page error: ${e.message}`));

    await page.goto(`${APP}/?signin=1`, { waitUntil: "networkidle2", timeout: 90000 });
    await page.waitForSelector("form.mr-signin input[type=email]", { timeout: 20000 });

    // Rule 7, measured rather than assumed.
    const ambiguity = await page.evaluate(() => ({
      emailFields: document.querySelectorAll('input[type="email"]').length,
      submitButtons: document.querySelectorAll('button[type="submit"]').length,
      inGate: document.querySelectorAll("form.mr-signin input[type=email]").length,
    }));
    console.log(`  page carries ${ambiguity.emailFields} email field(s) and ${ambiguity.submitButtons} submit button(s); ${ambiguity.inGate} inside form.mr-signin`);

    await page.click("form.mr-signin input[type=email]", { clickCount: 3 });
    await page.type("form.mr-signin input[type=email]", EMAIL);
    const typed = await page.$eval("form.mr-signin input[type=email]", (el) => el.value);
    if (typed !== EMAIL) throw new Error(`the gate's email field holds ${JSON.stringify(typed)}`);

    const otpCall = page.waitForResponse((r) => r.url().includes("/auth/v1/otp"), { timeout: 30000 });
    await page.$eval("form.mr-signin", (form) => form.querySelector('button[type="submit"]').click());
    try {
      const r = await otpCall;
      console.log(`  otp request -> ${r.status()}`);
    } catch {
      const shot = path.join(HERE, "signin-debug.png");
      await page.screenshot({ path: shot });
      const state = await page.evaluate(() => ({
        said: document.querySelector(".mr-signin-said")?.textContent?.trim() ?? null,
        buttons: [...document.querySelectorAll("form.mr-signin button")].map((b) => b.textContent.trim()),
      }));
      throw new Error(`the form never called /auth/v1/otp. state ${JSON.stringify(state)}; shot at ${shot}`);
    }

    let id = null;
    for (let i = 0; i < 40 && !id; i++) {
      await sleep(500);
      id = await latestMessageId();
    }
    if (!id) throw new Error("no sign-in mail arrived within 20s");

    const link = await signInLinkFrom(id);
    /* Same browser, so the PKCE verifier the form stored is the one the exchange reads. */
    await page.goto(link, { waitUntil: "networkidle2", timeout: 90000 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 90000 });

    const cookies = await browser.cookies();
    const authCookies = cookies.filter((c) => c.name.startsWith("sb-"));
    if (!authCookies.length) {
      throw new Error("callback completed but no sb-* cookie was set: the session did not stick");
    }

    /* ⛔ PROOF THE SESSION IS REAL ON THE SERVER. A signed-out render of `/` is a perfectly valid
     * page on this product (it falls through to the demo book), so "the page loaded" proves
     * nothing. `/api/corrections` answers 401 with no session, 402 with a session and no plan,
     * and 400 ("matchId and kind are required") with a session that has paid. One probe
     * separates all three, which also proves the seeded PRO row is being read. */
    const probe = await page.evaluate(() =>
      fetch("/api/corrections", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
        credentials: "include",
      })
        .then((r) => r.status)
        .catch(() => 0),
    );
    if (probe === 401) throw new Error("cookies were set but the server still reads signed-out");
    if (probe === 402) throw new Error("signed in, but the server says this login has no plan: the seeded matchrail_subscriptions row is not being read");

    fs.writeFileSync(
      OUT,
      JSON.stringify({ email: EMAIL, capturedAt: new Date().toISOString(), cookies: authCookies }, null, 2),
    );
    console.log(`signed in as ${EMAIL}`);
    console.log(`corrections probe returned ${probe} (401 signed out, 402 unpaid, 400 signed in and paid)`);
    console.log(`${authCookies.length} auth cookie(s) -> ${path.relative(process.cwd(), OUT)}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(String(err.message || err));
  process.exit(1);
});
