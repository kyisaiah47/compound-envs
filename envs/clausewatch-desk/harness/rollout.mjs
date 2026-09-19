/* ONE SCRIPTED ROLLOUT OF THE BROWSER TASK, START TO FINISH, AGAINST THE RUNNING APP.
 *
 * Reset -> open the console in its signed-in register -> put the Vantell lease on the file input
 * -> let the product read it -> read the rows.
 *
 * ⛔ IT ASSERTS ON THE RESPONSE, NOT ON THE PAGE. The upload control prints a sentence back
 * whatever happens, and that sentence is composed from whatever the route answered, so a page
 * that has re-rendered pleasantly is not evidence that anything was written.
 *
 * ⛔ AND `?signed-in=1` IS A REGISTER, NOT A TENANT. `src/app/page.tsx` says so in its own header.
 * The console's book is `buildBook()`, which runs the product's loop over the product's six demo
 * fixtures in memory for every visitor. The parameter unlocks the controls; the controls post to
 * the real routes with the real session cookie, and the upload route is the one of them that
 * writes to this tenant's database. The queue rows on screen belong to the in-memory book and
 * their ids do not exist in cw_signals, which is why the other four tasks are API tasks and drive
 * harness/act.mjs instead.
 *
 * ⛔ IT DOES NOT SCROLL AND DOES NOT SELECT TEXT. The file input is in frame the moment the
 * console renders in that register, so there is nothing to travel to.
 *
 *   node harness/rollout.mjs [--keep]      --keep leaves the rows in place for a grader run
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3754";
const DB_CONTAINER = process.env.DESK_DB_CONTAINER || "supabase_db_stack";
const FACTS = JSON.parse(fs.readFileSync(path.join(ROOT, "fixtures", "facts.json"), "utf8"));
const FIXTURE = path.join(ROOT, "fixtures", FACTS.upload.file_name);

const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

function reset() {
  execFileSync("docker", [
    "cp", path.join(ROOT, "sql", "02-seed.sql"), `${DB_CONTAINER}:/tmp/cw-seed.sql`,
  ]);
  execFileSync("docker", [
    "exec", DB_CONTAINER, "psql", "-U", "postgres", "-d", "postgres", "-q",
    "-v", "ON_ERROR_STOP=1", "-f", "/tmp/cw-seed.sql",
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

console.log("reset");
reset();
step(`contracts=${rows("select count(*) from cw_contracts")} clauses=${rows("select count(*) from cw_clauses")}`);

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

  await page.goto(`${APP}/?signed-in=1`, { waitUntil: "networkidle2", timeout: 60000 });
  step("console open in the signed-in register");

  /* The file input carries `hidden`, so the visible control is a button that clicks it. Putting
   * the file straight on the input is what a real upload does once that button has been pressed,
   * and it skips a click whose only job is to open a file dialog this harness cannot drive. */
  const inputs = await page.$$eval("input[type=file]", (els) => els.length);
  if (inputs !== 1) throw new Error(`${inputs} file inputs on this page, expected 1`);
  const input = await page.waitForSelector("input[type=file]", { timeout: 20000 });
  const uploaded = page.waitForResponse((r) => r.url().includes("/api/contracts/upload"), {
    timeout: 120000,
  });
  await input.uploadFile(FIXTURE);
  step(`put ${path.basename(FIXTURE)} on the file input`);

  const res = await uploaded;
  const body = await res.json().catch(() => ({}));
  step(`contracts/upload -> ${res.status()} ${JSON.stringify(body).slice(0, 200)}`);
  if (!res.ok()) ok = false;

  /* What the control printed back. `Upload.tsx` renders it as `<p className="note"
   * role="status"><b>{said}</b></p>`, and it composes nothing of its own: on a refusal it prints
   * the ROUTE'S own error string, so this line is the route speaking through the page. The
   * selector is the role rather than the class, because `.note` is a general paragraph style on
   * this site and `role="status"` is this one element.
   *
   * ⛔ THE FIRST CUT GUESSED `[class*='said']` from the state variable's name and matched
   * nothing, so it waited fifteen seconds and logged `null` while the upload had already
   * succeeded. A selector taken from a variable name is a selector taken from a description of
   * the markup rather than from the markup. */
  const said = await page
    .waitForFunction(
      () => document.querySelector('p.note[role="status"]')?.textContent?.trim() || null,
      { timeout: 15000 },
    )
    .then((h) => h.jsonValue())
    .catch(() => null);
  step(`the control says: ${JSON.stringify(said)}`);

  await new Promise((r) => setTimeout(r, 800));
  await page.screenshot({ path: path.join(HERE, "rollout-end.png"), fullPage: false });

  console.log("\nrows afterwards:");
  console.log(`  cw_contracts  ${rows("select count(*) from cw_contracts")}`);
  console.log(`  cw_clauses    ${rows("select count(*) from cw_clauses")}`);
  console.log(
    `  newest        ${rows("select title || ' state=' || coalesce(last_state,'?') || ' term_end=' || coalesce(term_end::text,'NULL') || ' blocked_by=' || blocked_by::text || ' chars=' || length(doc_text) from cw_contracts order by uploaded_at desc limit 1")}`,
  );
  console.log(
    `  its clauses   ${rows("select string_agg(kind || '=' || (case when found then 'found' else coalesce(not_found_reason,'?') end), ', ' order by kind) from cw_clauses where contract_id = (select id from cw_contracts order by uploaded_at desc limit 1)")}`,
  );
} catch (err) {
  ok = false;
  console.error(`\nFAILED: ${err.message}`);
} finally {
  /* Printed on success AND on failure. On a timeout this list is the whole diagnosis: it says
   * whether the page asked the upload route anything at all, which separates "the file never
   * reached the handler" from "the handler ran and the server refused". */
  console.log("\nrequests the page made:");
  if (!globalThis.__seen?.length) console.log("  (none)");
  for (const s of globalThis.__seen ?? []) console.log(`  ${String(s.status).padStart(3)}  ${s.path}`);
  await browser.close();
}

if (!process.argv.includes("--keep")) reset();
process.exit(ok ? 0 : 1);
