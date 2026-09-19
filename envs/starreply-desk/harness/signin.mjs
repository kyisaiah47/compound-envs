/* Sign in once and freeze the session, so an episode starts on the queue rather than at a gate.
 *
 * ⛔ THE SIGN-IN IS REAL, NOT A FORGED COOKIE. starreply has no passwords: `LandingAuth.tsx` says
 * so in as many words and offers exactly two controls, Google OAuth and `signInWithOtp`. OTP runs
 * under PKCE, so the code verifier lives in the browser that asked for the link and only that
 * browser can complete the exchange. Writing a cookie by hand means guessing @supabase/ssr's
 * storage key and its chunking, and a guess that is subtly wrong renders a signed-out page while
 * every check here reports success. So this drives the real gate, reads the real mail out of the
 * local Mailpit, follows the real callback, and copies out whatever cookies the app actually set.
 *
 * ⛔ THE GATE IS A DIALOG BEHIND `?signin=1`, NOT A PAGE. `/` renders the console and mounts
 * `LandingAuth`; the email field only exists once that parameter is read. There is no /sign-in
 * route in this product.
 *
 * ⛔ RULE 7, SELECTORS ARE AMBIGUOUS. `/` carries the gate's email field AND `ListCapture`'s own
 * mailing-list field, both `input[type=email]`, and a `button[type=submit]` selector can reach
 * either form. The gate's control is addressed through the dialog that owns it.
 *
 *   node harness/signin.mjs            # writes harness/session.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3752";
const MAILPIT = process.env.DESK_MAILPIT_URL || "http://127.0.0.1:54324";
const EMAIL = process.env.DESK_EMAIL || "desk@bloomwelldental.example";
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

    /* `?next=/` so the callback lands back on the console. Its own default is /dashboard, which
     * this tree does not serve. */
    await page.goto(`${APP}/?signin=1&next=%2F`, { waitUntil: "networkidle2", timeout: 60000 });
    await page.waitForSelector('[role="dialog"] input[type="email"]', { timeout: 20000 });

    await page.click('[role="dialog"] input[type="email"]', { clickCount: 3 });
    await page.type('[role="dialog"] input[type="email"]', EMAIL);
    const typed = await page.$eval('[role="dialog"] input[type="email"]', (el) => el.value);
    if (typed !== EMAIL) throw new Error(`the email field holds ${JSON.stringify(typed)}`);

    const otpCall = page.waitForResponse((r) => r.url().includes("/auth/v1/otp"), { timeout: 20000 });
    await page.$eval('[role="dialog"] input[type="email"]', (el) => {
      const form = el.closest("form");
      if (!form) throw new Error("the gate's email field is not inside a form");
      form.querySelector('button[type="submit"]').click();
    });
    try {
      const r = await otpCall;
      console.log(`  otp request -> ${r.status()}`);
    } catch {
      const shot = path.join(HERE, "signin-debug.png");
      await page.screenshot({ path: shot });
      const state = await page.evaluate(() => ({
        buttons: [...document.querySelectorAll('[role="dialog"] button')].map((b) => b.textContent.trim()),
        said: document.querySelector('[role="dialog"] .gateSay')?.textContent?.trim() ?? null,
      }));
      throw new Error(`the gate never called /auth/v1/otp. state ${JSON.stringify(state)}; shot at ${shot}`);
    }

    let id = null;
    for (let i = 0; i < 40 && !id; i++) {
      await sleep(500);
      id = await latestMessageId();
    }
    if (!id) throw new Error("no sign-in mail arrived within 20s");

    const link = await signInLinkFrom(id);
    /* Same browser, so the PKCE verifier the gate stored is the one the exchange reads. */
    await page.goto(link, { waitUntil: "networkidle2", timeout: 60000 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

    const cookies = await browser.cookies();
    const authCookies = cookies.filter((c) => c.name.startsWith("sb-"));
    if (!authCookies.length) {
      throw new Error("callback completed but no sb-* cookie was set: the session did not stick");
    }

    /* ⛔ PROOF THE SESSION IS REAL ON THE SERVER. A signed-out render of `/` is a perfectly valid
     * page on this product, so "the page loaded" proves nothing. `/api/autonomy` answers 401 with
     * no session and 400 ("Nothing to change.") with one, so the status separates the two. */
    const probe = await page.evaluate(() =>
      fetch("/api/autonomy", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
        credentials: "include",
      })
        .then((r) => r.status)
        .catch(() => 0),
    );
    if (probe === 401) throw new Error("cookies were set but the server still reads signed-out");

    fs.writeFileSync(
      OUT,
      JSON.stringify({ email: EMAIL, capturedAt: new Date().toISOString(), cookies: authCookies }, null, 2),
    );
    console.log(`signed in as ${EMAIL}`);
    console.log(`autonomy probe returned ${probe} (401 would mean signed out)`);
    console.log(`${authCookies.length} auth cookie(s) -> ${path.relative(process.cwd(), OUT)}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(String(err.message || err));
  process.exit(1);
});
