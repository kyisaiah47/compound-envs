/* Sign in once and freeze the session, so an episode starts at the desk rather than at a login.
 *
 * ⛔ THE SIGN-IN IS REAL, NOT A FORGED COOKIE. `components/Auth.tsx` signs in with
 * `signInWithOtp` under PKCE, so the code verifier lives in the browser that asked for the link
 * and only that browser can complete the exchange. Writing a cookie by hand means guessing
 * @supabase/ssr's storage key and its chunking, and a guess that is subtly wrong produces a page
 * that renders signed-out while every check here reports success. So this drives the real dialog,
 * reads the real mail out of the local Mailpit, follows the real callback, and copies out
 * whatever cookies the app actually set.
 *
 * Mailpit is the local Supabase stack's own mail sink on 54324. Nothing leaves the machine and no
 * mail client is involved.
 *
 *   node harness/signin.mjs            # writes harness/session.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3754";
const MAILPIT = process.env.DESK_MAILPIT_URL || "http://127.0.0.1:54324";
const FACTS = JSON.parse(fs.readFileSync(path.join(ROOT, "fixtures", "facts.json"), "utf8"));
const EMAIL = process.env.DESK_EMAIL || FACTS.desk_email;
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

    /* ⛔ THERE IS NO /sign-in PAGE. `components/Auth.tsx`'s own header says so: the whole front
     * door is a native <dialog> mounted in the root layout, opened by `?signin=1`, which the
     * component reads out of `location.search` on load. */
    await page.goto(`${APP}/?signin=1`, { waitUntil: "networkidle2", timeout: 60000 });
    await page.waitForSelector("dialog.gate[open]", { timeout: 20000 });

    /* ⛔ `input[type=email]` IS AMBIGUOUS ON THIS PAGE and the first match is the wrong form.
     * `components/Chrome.tsx` renders `ListCapture` in the footer of every page, so the document
     * carries the auth field AND a mailing-list field whose buttons read "Email me a sign in
     * link" and (in the footer) something else entirely. Typing into the wrong one sends no auth
     * mail, errors nowhere, and leaves this script waiting on a message that is never coming. The
     * field is addressed through the dialog it belongs to instead. */
    const field = "dialog.gate form input[type=email]";
    const count = await page.$$eval("input[type=email]", (els) => els.length);
    console.log(`  ${count} email field(s) in the document; using ${field}`);

    await page.click(field, { clickCount: 3 });
    await page.type(field, EMAIL);
    const typed = await page.$eval(field, (el) => el.value);
    if (typed !== EMAIL) throw new Error(`the auth field holds ${JSON.stringify(typed)}`);

    const otpCall = page.waitForResponse((r) => r.url().includes("/auth/v1/otp"), {
      timeout: 20000,
    });
    /* Submitted through the form the field belongs to, never by button index. */
    await page.$eval(field, (el) => {
      const form = el.closest("form");
      if (!form) throw new Error("the auth field is not inside a form");
      form.querySelector('button[type="submit"]').click();
    });
    try {
      const r = await otpCall;
      console.log(`  otp request -> ${r.status()}`);
    } catch {
      const shot = path.join(HERE, "signin-debug.png");
      await page.screenshot({ path: shot });
      const state = await page.evaluate(() => ({
        dialogOpen: !!document.querySelector("dialog.gate[open]"),
        buttons: [...document.querySelectorAll("dialog.gate button")].map((b) =>
          b.textContent.trim(),
        ),
        said: document.querySelector(".gate-said")?.textContent?.trim() ?? null,
      }));
      throw new Error(
        `the dialog never called /auth/v1/otp. page state ${JSON.stringify(state)}; shot at ${shot}`,
      );
    }

    let id = null;
    for (let i = 0; i < 40 && !id; i++) {
      await sleep(500);
      id = await latestMessageId();
    }
    if (!id) throw new Error("no sign-in mail arrived within 20s");

    const link = await signInLinkFrom(id);
    /* Same browser, so the PKCE verifier the dialog stored is the one the exchange reads. */
    await page.goto(link, { waitUntil: "networkidle2", timeout: 60000 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

    const cookies = await browser.cookies();
    const authCookies = cookies.filter((c) => c.name.startsWith("sb-"));
    if (!authCookies.length) {
      throw new Error("callback completed but no sb-* cookie was set: the session did not stick");
    }

    /* ⛔ PROOF THE SESSION IS REAL ON THE SERVER, not just that a cookie exists. A signed-out
     * render of this app is a perfectly valid page, and every route here answers on the service
     * client, so "the page loaded" proves nothing at all. `/api/queue/kill` with no body is the
     * cheapest probe that runs the full gate: requireMember, then requireWriter, then the missing
     * signalId. 401 means no session. 400 means the session is good and the body was empty, which
     * is the answer this wants. Nothing is written either way. */
    const probe = await page.evaluate(() =>
      fetch("/api/queue/kill", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: "{}",
        credentials: "include",
      })
        .then(async (r) => ({ status: r.status, body: (await r.text()).slice(0, 120) }))
        .catch(() => ({ status: 0, body: "no answer" })),
    );
    if (probe.status === 401) {
      throw new Error("cookies were set but the server still reads signed-out");
    }
    if (probe.status === 403) {
      throw new Error(
        `signed in, but the account has no usable membership: ${probe.body}.` +
          " The seed writes the cw_members row; check sql/02-seed.sql was applied.",
      );
    }

    fs.writeFileSync(
      OUT,
      JSON.stringify(
        { email: EMAIL, capturedAt: new Date().toISOString(), cookies: authCookies },
        null,
        2,
      ),
    );
    console.log(`signed in as ${EMAIL}`);
    console.log(`queue/kill probe returned ${probe.status} ${probe.body}`);
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
