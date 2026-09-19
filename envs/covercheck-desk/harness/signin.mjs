/* Sign in once and freeze the session, so an episode starts at the console rather than at a form.
 *
 * ⛔ THE SIGN-IN IS REAL, NOT A FORGED COOKIE. CoverCheck signs in with email and password through
 * supabase-js in the BROWSER (`browserSupabase().auth.signInWithPassword`, Bar.tsx), and
 * @supabase/ssr writes the session cookie itself, chunked, under a key derived from the project
 * ref. Writing that by hand means guessing the key and the chunking, and a guess that is subtly
 * wrong produces a page that renders signed-out while every check here reports success. So this
 * drives the real form and copies out whatever cookies the app actually set.
 *
 *   node harness/signin.mjs            # writes harness/session.json
 *
 * ⛔ AND THE TAB MATTERS. The console's bar has four tabs and only one of them carries the
 * sign-in form. `input[type=email]` alone is ambiguous on this page: the footer's list-capture
 * form has one too, and typing into that one sends nothing and errors nowhere. The form is
 * addressed through the tab that owns it and then through the field's own <form>.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3764";
const EMAIL = process.env.DESK_EMAIL || "desk@harborridgepm.example";
const PASSWORD = process.env.DESK_PASSWORD || "covercheck-fixture-password";
const OUT = path.join(HERE, "session.json");

async function main() {
  const browser = await launchSafe(puppeteer, { headless: true });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  try {
    page.on("pageerror", (e) => console.error(`  page error: ${e.message}`));

    await page.goto(`${APP}/?auth=1`, { waitUntil: "networkidle2", timeout: 60000 });

    // Open the Sign in tab by its own label, never by index: the tab strip drops that tab
    // entirely once a member is signed in, so a positional selector means something different
    // depending on state.
    const opened = await page.evaluate(() => {
      const tab = [...document.querySelectorAll('[role="tab"]')].find(
        (b) => b.textContent.trim().toLowerCase() === "sign in",
      );
      if (!tab) return false;
      tab.click();
      return true;
    });
    if (!opened) throw new Error("no tab reads 'Sign in' on the console");

    await page.waitForSelector('.bar form input[name="email"]', { timeout: 20000 });
    await page.type('.bar form input[name="email"]', EMAIL);
    await page.type('.bar form input[name="password"]', PASSWORD);

    const tokenCall = page.waitForResponse(
      (r) => r.url().includes("/auth/v1/token"),
      { timeout: 20000 },
    );
    await page.$eval('.bar form input[name="email"]', (el) => {
      el.closest("form").querySelector('button[type="submit"]').click();
    });

    const tokenRes = await tokenCall.catch(async () => {
      const shot = path.join(HERE, "signin-debug.png");
      await page.screenshot({ path: shot });
      throw new Error(`the form never called /auth/v1/token; shot at ${shot}`);
    });
    console.log(`  token request -> ${tokenRes.status()}`);
    if (!tokenRes.ok()) {
      throw new Error(`sign-in refused: ${JSON.stringify(await tokenRes.json().catch(() => ({})))}`);
    }

    // The form sends the browser to /auth/callback, which provisions an org for a brand new
    // account and then redirects to the dashboard, which redirects to the console.
    await page.waitForNavigation({ waitUntil: "networkidle2", timeout: 60000 }).catch(() => {});
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

    const cookies = (await browser.cookies()).filter((c) => c.name.startsWith("sb-"));
    if (!cookies.length) throw new Error("sign-in succeeded but no sb-* cookie was set");

    /* ⛔ PROOF THE SESSION IS REAL ON THE SERVER. A signed-out render of this console is a
     * perfectly valid page showing the demo book, so "the page loaded" proves nothing at all.
     * GET /api/vendors answers 401 for a stranger and a vendor list for a member. */
    const probe = await page.evaluate(() =>
      fetch("/api/vendors", { credentials: "include" })
        .then(async (r) => ({ status: r.status, body: await r.json().catch(() => ({})) }))
        .catch(() => ({ status: 0, body: {} })),
    );
    if (probe.status !== 200) {
      throw new Error(`cookies were set but /api/vendors answered ${probe.status}`);
    }

    fs.writeFileSync(
      OUT,
      JSON.stringify({ email: EMAIL, capturedAt: new Date().toISOString(), cookies }, null, 2),
    );
    console.log(`signed in as ${EMAIL}`);
    console.log(`  /api/vendors -> 200, ${(probe.body.vendors ?? []).length} vendors`);
    console.log(`  ${cookies.length} auth cookie(s) -> ${path.relative(process.cwd(), OUT)}`);
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(String(err.message || err));
  process.exit(1);
});
