/* One scripted rollout of a browser task, start to finish, against the running app.
 *
 *   node harness/rollout.mjs subscribe [--keep]
 *   node harness/rollout.mjs signup    [--keep]
 *
 * --keep leaves the rows in place for a grader run. Without it the fixture is put back.
 *
 * IT ASSERTS ON RESPONSES, NOT ON THE PAGE. Each step waits for the request the app actually
 * makes and records its status. A page that has re-rendered pleasantly is not evidence that
 * anything was written, which is the whole premise of this repo.
 *
 * AND EVERY CONTROL IS ADDRESSED BY SOMETHING THAT IDENTIFIES IT. /sign-in carries three
 * buttons: two tabs that switch the form between signing in and making an account, both
 * type=button, and then the submit. `page.click("button")` presses the FIRST one, which is the
 * "Sign in" tab, and that changes nothing and errors nowhere. The account is never made and the
 * run looks like it did the work.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.STANDUP_APP_URL || "http://127.0.0.1:3745";
const DB_CONTAINER = process.env.STANDUP_DB_CONTAINER || "supabase_db_stack";

const TASK = process.argv[2];
if (!["subscribe", "signup"].includes(TASK)) {
  console.error("usage: node harness/rollout.mjs <subscribe|signup> [--keep]");
  process.exit(2);
}

/* Typed exactly as the task states it, capitals included. /api/subscribe lowercases and trims
 * before it writes, and an input[type=email] strips surrounding whitespace on its own, so the
 * row the product makes is the lower-cased one. */
const NEW_READER = "N.Calloway@Brightpath.example";
const BUYER = "e.ferraro@northgatelabs.example";
const BUYER_PASSWORD = "standup-fixture-pw";

function reset() {
  execFileSync("docker", ["cp", path.join(ROOT, "sql", "02-seed.sql"), `${DB_CONTAINER}:/tmp/seed.sql`]);
  execFileSync("docker", ["exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "postgres", "-q", "-f", "/tmp/seed.sql"]);
}

function rows(sql) {
  return execFileSync(
    "docker",
    ["exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "postgres", "-t", "-A", "-c", sql],
    { encoding: "utf8" },
  ).trim();
}

const t0 = Date.now();
const step = (s) => console.log(`  ${String(Date.now() - t0).padStart(6)}ms  ${s}`);

console.log(`reset (${TASK})`);
reset();
step(`subscribers=${rows("select count(*) from standup_subscribers")} profiles=${rows("select count(*) from standup_profiles")}`);

const browser = await launchSafe(puppeteer, { headless: true });
let ok = true;
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });

  const seen = (globalThis.__seen = []);
  page.on("response", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/") || u.pathname.startsWith("/auth/v1/")) {
      seen.push({ path: u.pathname, status: r.status() });
    }
  });

  if (TASK === "subscribe") {
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });
    step("ledger open");

    /* No scroll. The signup section is a named anchor the page already carries, so the element
     * is brought into view by its own id rather than by a pixel amount, and nothing is
     * selected. */
    const field = await page.waitForSelector("#subscribe input[name=email]", { timeout: 20000 });
    await field.click();
    await field.type(NEW_READER, { delay: 12 });
    step(`typed ${NEW_READER}`);

    const posted = page.waitForResponse((r) => r.url().includes("/api/subscribe"), { timeout: 60000 });
    const pressed = await page.evaluate(() => {
      const form = document.querySelector("#subscribe form");
      const b = form && form.querySelector("button[type=submit]");
      if (!b) return false;
      b.click();
      return true;
    });
    if (!pressed) throw new Error("no submit button inside #subscribe form");
    const res = await posted;
    step(`/api/subscribe -> ${res.status()} ${JSON.stringify(await res.json().catch(() => ({}))).slice(0, 120)}`);
    if (!res.ok()) ok = false;

    console.log("\nrows afterwards:");
    console.log(`  subscribers   ${rows("select count(*) from standup_subscribers")}`);
    console.log(`  the new one   ${rows("select email || ' confirmed=' || confirmed || ' source=' || source from standup_subscribers order by created_at desc limit 1")}`);
  }

  if (TASK === "signup") {
    await page.goto(`${APP}/sign-in`, { waitUntil: "networkidle2", timeout: 60000 });
    step("sign-in open");

    /* The tab, by its own words. An index would press "Sign in" and the form would look
     * identical while doing the opposite thing. */
    const tabbed = await page.evaluate(() => {
      const b = [...document.querySelectorAll("button[type=button]")].find(
        (el) => el.textContent.trim().toLowerCase() === "create an account",
      );
      if (!b) return false;
      b.click();
      return true;
    });
    if (!tabbed) throw new Error("no tab reads 'Create an account' on /sign-in");
    step("switched to Create an account");

    await (await page.waitForSelector("form.auth input#email", { timeout: 20000 })).type(BUYER, { delay: 12 });
    await (await page.waitForSelector("form.auth input#password", { timeout: 20000 })).type(BUYER_PASSWORD, { delay: 12 });
    step(`typed ${BUYER}`);

    const signed = page.waitForResponse((r) => r.url().includes("/auth/v1/signup"), { timeout: 60000 });
    const pressed = await page.evaluate(() => {
      const b = document.querySelector("form.auth button[type=submit]");
      if (!b) return false;
      b.click();
      return true;
    });
    if (!pressed) throw new Error("no submit button on the auth form");
    const res = await signed;
    step(`/auth/v1/signup -> ${res.status()}`);
    if (!res.ok()) ok = false;

    /* The trigger runs inside the insert, so the rows are there the moment the response is. The
     * beat is for the page, not for the database. */
    await new Promise((r) => setTimeout(r, 800));
    console.log("\nrows afterwards:");
    console.log(`  profiles      ${rows("select count(*) from standup_profiles")}`);
    console.log(`  the buyer     ${rows("select email || ' plan=' || plan || ' cus=' || coalesce(stripe_customer_id,'-') from standup_profiles where email = '" + BUYER + "'")}`);
    console.log(`  parked row    ${rows("select email || ' claimed=' || coalesce(claimed_at::text,'never') from standup_pending_members where email = '" + BUYER + "'")}`);
  }

  await new Promise((r) => setTimeout(r, 900));
  await page.screenshot({ path: path.join(HERE, `rollout-${TASK}.png`), fullPage: false });
} catch (err) {
  ok = false;
  console.error(`\nFAILED: ${err.message}`);
} finally {
  /* Printed on success AND on failure. On a timeout this list is the whole diagnosis: it says
   * whether the app was asked to do anything at all, which separates "the control was never
   * pressed" from "the handler ran and the server refused". */
  console.log("\nrequests the app made:");
  if (!globalThis.__seen?.length) console.log("  (none)");
  for (const s of globalThis.__seen ?? []) console.log(`  ${String(s.status).padStart(3)}  ${s.path}`);
  await browser.close();
}

if (!process.argv.includes("--keep")) reset();
process.exit(ok ? 0 : 1);
