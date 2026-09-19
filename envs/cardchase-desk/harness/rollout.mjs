/* One scripted rollout of a browser task, start to finish, against the running app.
 *
 *   node harness/rollout.mjs approve [--keep]
 *   node harness/rollout.mjs kill    [--keep]
 *
 * --keep leaves the rows in place so a grader can read them.
 *
 * ⛔ IT ASSERTS ON THE RESPONSE, NOT ON THE PAGE. Each step waits for the request the app
 * actually makes and records its status. A page that has re-rendered pleasantly is not evidence
 * that anything was written, which is the whole premise of this repo. The console's own control
 * calls `window.location.reload()` the moment its fetch resolves, so a rollout that watched the
 * DOM would be reading a page that is already being replaced.
 *
 * ⛔ AND THE ROW IS ADDRESSED BY ITS CUSTOMER, NEVER BY POSITION. The river is ranked by what
 * churn costs per month, so the first row is the $890/mo one, which is the row the gate has
 * permanently stopped and the one row that draws no controls at all. Two rows in the fixture
 * carry the same company, the same money and the same decline code, so the customer's name is
 * the only thing that tells them apart.
 *
 * ⛔ AND THE BUTTON IS ADDRESSED BY ITS OWN TEXT. Approve and Kill are both `.cc-btn`; Approve
 * carries an extra modifier class and Kill does not, so `.cc-btn` finds Approve first whenever
 * both are on screen. A rollout written that way kills nothing and approves something.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.CARDCHASE_APP_URL || "http://127.0.0.1:3756";
const DB_CONTAINER = process.env.CARDCHASE_DB_CONTAINER || "supabase_db_stack";

const TASKS = {
  approve: { customer: "Priya Raghunathan", button: "approve", route: "/api/queue/approve" },
  kill: { customer: "Wendell Achebe", button: "kill", route: "/api/queue/undo" },
};

const which = process.argv[2];
const task = TASKS[which];
if (!task) {
  console.error(`usage: node rollout.mjs <${Object.keys(TASKS).join("|")}> [--keep]`);
  process.exit(2);
}

const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

function reset() {
  execFileSync("docker", ["cp", path.join(ROOT, "sql", "02-seed.sql"), `${DB_CONTAINER}:/tmp/cc-seed.sql`]);
  execFileSync("docker", [
    "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "postgres", "-q", "-f", "/tmp/cc-seed.sql",
  ]);
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

console.log(`reset (${which})`);
reset();
step(
  `approved retries=${rows("select count(*) from cardchase_retries where approved_at is not null")}` +
    ` cancelled=${rows("select count(*) from cardchase_retries where status = 'cancelled'")}` +
    ` clean approvals=${rows("select plan_rules ->> 'autonomy_clean_approvals' from cardchase_ladder where user_id = '00000000-0000-4000-9000-0000000000a1'")}`,
);

const browser = await launchSafe(puppeteer, { headless: true });
let ok = true;
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await browser.setCookie(...session.cookies);

  const seen = (globalThis.__seen = []);
  page.on("response", (r) => {
    const u = new URL(r.url()).pathname;
    if (u.startsWith("/api/")) seen.push({ path: u, status: r.status() });
  });

  await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

  /* The tenant line is the proof the console is on the OWNER's book. Signed out, this page is a
   * complete, plausible queue on the shared demo account, and every step below would run against
   * it without erroring. */
  const tenant = await page.$eval(".cc-bar", (el) => el.textContent.trim()).catch(() => "");
  if (!/Northlight Gear/.test(tenant)) {
    throw new Error(`the console is not on the owner's book. bar reads: ${tenant.slice(0, 160)}`);
  }
  step(`console open on ${tenant.match(/Northlight Gear[^\s]*/)?.[0] ?? "the owner's book"}`);

  /* ⛔ THE ROW IS OPENED ONLY IF IT IS SHUT. The console opens one row on load, and it opens the
   * one whose window is counting down, which is the Kill task's row. Clicking a row that is
   * already open closes it, and the pane that carries the control is not rendered while it is
   * shut. */
  const opened = await page.evaluate((name) => {
    const row = [...document.querySelectorAll("article.cc-row")].find(
      (el) => el.querySelector(".cc-who")?.textContent.trim() === name,
    );
    if (!row) return { found: false };
    if (row.dataset.open !== "true") {
      row.querySelector("button.cc-row-btn").click();
      return { found: true, clicked: true };
    }
    return { found: true, clicked: false };
  }, task.customer);
  if (!opened.found) {
    const names = await page.$$eval(".cc-who", (els) => els.map((e) => e.textContent.trim()));
    throw new Error(`no row for ${task.customer}. the river shows: ${JSON.stringify(names)}`);
  }
  step(`${task.customer}'s row ${opened.clicked ? "opened" : "was already open"}`);

  const posted = page.waitForResponse((r) => r.url().includes(task.route), { timeout: 30000 });
  const pressed = await page.evaluate(
    (name, word) => {
      const row = [...document.querySelectorAll("article.cc-row")].find(
        (el) => el.querySelector(".cc-who")?.textContent.trim() === name,
      );
      const btn = [...row.querySelectorAll("button.cc-btn")].find(
        (b) => b.textContent.trim().toLowerCase() === word,
      );
      if (!btn) {
        return {
          ok: false,
          buttons: [...row.querySelectorAll("button")].map((b) => b.textContent.trim()),
        };
      }
      btn.click();
      return { ok: true };
    },
    task.customer,
    task.button,
  );
  if (!pressed.ok) {
    throw new Error(
      `no control reads ${JSON.stringify(task.button)} on that row. it carries: ${JSON.stringify(pressed.buttons)}`,
    );
  }
  step(`pressed ${task.button}`);

  const res = await posted;
  const body = await res.json().catch(() => ({}));
  step(`${task.route} -> ${res.status()} ${JSON.stringify(body).slice(0, 140)}`);
  if (!res.ok()) ok = false;

  /* The control reloads the page as soon as its fetch resolves. A beat, so the last frame is the
   * console re-rendered on the rows that were just written. */
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(HERE, `rollout-${which}.png`), fullPage: false });

  console.log("\nrows afterwards:");
  console.log(
    `  approved retries   ${rows("select count(*) from cardchase_retries where approved_at is not null")}`,
  );
  console.log(
    `  cancelled retries  ${rows("select count(*) from cardchase_retries where status = 'cancelled'")}`,
  );
  console.log(
    `  clean approvals    ${rows("select plan_rules ->> 'autonomy_clean_approvals' from cardchase_ladder where user_id = '00000000-0000-4000-9000-0000000000a1'")}`,
  );
  console.log(
    `  receipts written   ${rows("select string_agg(kind || ':' || n, ' ') from (select kind, count(*) n from cardchase_events where user_id = '00000000-0000-4000-9000-0000000000a1' group by kind order by kind) k")}`,
  );
} catch (err) {
  ok = false;
  console.error(`\nFAILED: ${err.message}`);
} finally {
  /* Printed on success AND on failure. On a timeout this list is the whole diagnosis: it says
   * whether the app called the route at all, which separates "the control was never pressed"
   * from "the route ran and refused". */
  console.log("\nrequests the app made:");
  if (!globalThis.__seen?.length) console.log("  (none)");
  for (const s of globalThis.__seen ?? []) console.log(`  ${String(s.status).padStart(3)}  ${s.path}`);
  await browser.close();
}

if (!process.argv.includes("--keep")) reset();
process.exit(ok ? 0 : 1);
