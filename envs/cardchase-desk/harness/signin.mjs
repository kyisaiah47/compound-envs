/* Sign in once and freeze the session, so an episode starts on the console rather than at a gate.
 *
 * ⛔ THE SIGN IN IS REAL, NOT A FORGED COOKIE. CardChase has no password form and no /login page:
 * the whole front door is `components/Auth.tsx`, a native <dialog> that `/?signin=1` opens, and
 * it offers Google OAuth or a one time email link. The link runs under PKCE, so the code
 * verifier lives in the browser that asked for it and only that browser can complete the
 * exchange. Writing a cookie by hand means guessing @supabase/ssr's storage key and its chunking,
 * and a guess that is subtly wrong produces a console that renders the READ ONLY DEMO BOOK while
 * every check here reports success. That failure is invisible: the demo book is a complete,
 * plausible queue. So this drives the real dialog, reads the real mail out of the local Mailpit,
 * completes the real callback, and copies out whatever cookies the app actually set.
 *
 * ⛔ AND IT LANDS BACK ON 127.0.0.1 BY HAND, WHICH IS NOT DECORATION. Measured 2026-09-19 against
 * this app on 3756: GoTrue's /verify redirects correctly to `127.0.0.1:3756/auth/callback?code=`,
 * the route exchanges the code and sets `sb-127-auth-token` on host 127.0.0.1, and then redirects
 * to `next` against `new URL(req.url).origin`, which Next resolves to `localhost:3756`. Browsers
 * scope cookies by HOST and localhost is a different host from 127.0.0.1, so the page that comes
 * back carries no session at all: the console renders the read only demo book, and `GET
 * /api/workspace-key` answers 401 while a perfectly good session cookie sits on the other name.
 * `scripts/up.sh` binds the server to 127.0.0.1 so the origin matches, and this script navigates
 * back to the app's own origin before it reads anything, because one fix that depends on how the
 * server was started is not a fix.
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
const APP = process.env.CARDCHASE_APP_URL || "http://127.0.0.1:3756";
const MAILPIT = process.env.CARDCHASE_MAILPIT_URL || "http://127.0.0.1:54324";
const EMAIL = process.env.CARDCHASE_EMAIL || "ops@northlight-gear.example";
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

async function verifyLinkFrom(id) {
  const res = await fetch(`${MAILPIT}/api/v1/message/${id}`);
  const msg = await res.json();
  const body = `${msg.Text || ""}\n${msg.HTML || ""}`;
  const urls = body.match(/https?:\/\/[^\s"'<>]+/g) || [];
  const link = urls.find((u) => u.includes("/auth/v1/verify") || u.includes("token="));
  if (!link) throw new Error(`no sign in link in message ${id}; urls=${JSON.stringify(urls)}`);
  return link.replace(/&amp;/g, "&");
}

/** The authorization code GoTrue hands back, taken off the redirect it refuses to send to us. */
async function codeFrom(verifyLink) {
  const res = await fetch(verifyLink, { redirect: "manual" });
  const location = res.headers.get("location");
  if (!location) throw new Error(`/verify answered ${res.status} with no redirect`);
  const url = new URL(location);
  const code = url.searchParams.get("code");
  if (code) return code;
  if (url.hash.includes("access_token")) {
    throw new Error(
      "/verify returned an implicit-flow fragment; this app's client is PKCE and expects ?code=",
    );
  }
  throw new Error(`no authorization code in the redirect: ${location.slice(0, 200)}`);
}

async function main() {
  await clearMailbox();

  const browser = await launchSafe(puppeteer, { headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  try {
    page.on("pageerror", (e) => console.error(`  page error: ${e.message}`));
    page.on("requestfailed", (r) => console.error(`  request failed: ${r.url()}`));

    await page.goto(`${APP}/?signin=1`, { waitUntil: "networkidle2", timeout: 60000 });

    /* ⛔ ADDRESSED INSIDE THE DIALOG, NOT ON THE PAGE. The console carries a mailing list capture
     * with its own email field and its own submit button, and `input[type=email]` alone finds it
     * first on some renders. Typing the address into that one subscribes a fixture account to a
     * newsletter, nothing errors, and no sign in mail is ever sent. */
    await page.waitForSelector("dialog.cc-auth[open] input[type=email]", { timeout: 20000 });
    await page.click("dialog.cc-auth[open] input[type=email]", { clickCount: 3 });
    await page.type("dialog.cc-auth[open] input[type=email]", EMAIL);
    const typed = await page.$eval("dialog.cc-auth[open] input[type=email]", (el) => el.value);
    if (typed !== EMAIL) throw new Error(`the email field holds ${JSON.stringify(typed)}`);

    const otpCall = page.waitForResponse((r) => r.url().includes("/auth/v1/otp"), { timeout: 20000 });
    await page.$eval("dialog.cc-auth[open] input[type=email]", (el) => {
      const form = el.closest("form");
      if (!form) throw new Error("the email field is not inside a form");
      form.querySelector('button[type="submit"]').click();
    });
    try {
      const r = await otpCall;
      console.log(`  otp request -> ${r.status()}`);
      if (r.status() >= 400) {
        throw new Error(`GoTrue refused the one time link: ${JSON.stringify(await r.json().catch(() => ({})))}`);
      }
    } catch (err) {
      const shot = path.join(HERE, "signin-debug.png");
      await page.screenshot({ path: shot });
      const state = await page.evaluate(() => ({
        dialogOpen: !!document.querySelector("dialog.cc-auth[open]"),
        buttons: [...document.querySelectorAll("dialog.cc-auth button")].map((b) => b.textContent.trim()),
        said: document.querySelector(".cc-auth-said")?.textContent?.trim() ?? null,
      }));
      throw new Error(`${err.message}. page state ${JSON.stringify(state)}; shot at ${shot}`);
    }

    let id = null;
    for (let i = 0; i < 40 && !id; i++) {
      await sleep(500);
      id = await latestMessageId();
    }
    if (!id) throw new Error("no sign in mail arrived within 20s");

    const link = await verifyLinkFrom(id);
    const code = await codeFrom(link);
    /* Same browser, so the PKCE verifier the dialog stored is the one this exchange reads. */
    await page.goto(`${APP}/auth/callback?code=${encodeURIComponent(code)}&next=/`, {
      waitUntil: "networkidle2",
      timeout: 60000,
    });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

    const cookies = await browser.cookies();
    const authCookies = cookies.filter((c) => c.name.startsWith("sb-"));
    if (!authCookies.length) {
      throw new Error("the callback completed and no sb-* cookie was set: the session did not stick");
    }

    /* ⛔ PROOF THE SESSION IS REAL ON THE SERVER, not that a cookie exists. A signed out render of
     * this app is a complete, valid page: the console runs on the demo book and draws a full
     * queue. `GET /api/workspace-key` is the cheapest owner-scoped read in the product, it writes
     * nothing, and it answers 401 when the server reads signed out. */
    const probe = await page.evaluate(() =>
      fetch("/api/workspace-key", { credentials: "include" }).then((r) => r.status).catch(() => 0),
    );
    if (probe === 401) throw new Error("cookies were set and the server still reads signed out");
    if (probe !== 200) throw new Error(`the signed-in probe answered ${probe}, expected 200`);

    /* ⛔ AND PROOF IT IS THE OWNER'S BOOK ON SCREEN, not the demo's. `loadTenant` returns mode
     * "live" only for a real session that is not the demo address, and the console prints the
     * tenant label off the owner's own voice profile. A page that renders the demo book here is
     * the exact failure a forged cookie produces. */
    const label = await page.evaluate(
      () => document.querySelector(".cc-bar")?.textContent?.trim() ?? document.body.innerText.slice(0, 400),
    );
    if (!/Northlight Gear/.test(label)) {
      throw new Error(`the console is not rendering the owner's book. bar reads: ${label.slice(0, 200)}`);
    }

    fs.writeFileSync(
      OUT,
      JSON.stringify({ email: EMAIL, capturedAt: new Date().toISOString(), cookies: authCookies }, null, 2),
    );
    console.log(`signed in as ${EMAIL}`);
    console.log(`workspace-key probe returned ${probe}`);
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
