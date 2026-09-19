/* One scripted rollout of the browser task, start to finish, against the running app.
 *
 * Reset -> open the ledger -> put a statement on the file input -> let the app ticket it, upload
 * it to storage and confirm it -> press Start the audit -> read the rows.
 *
 * ⛔ IT ASSERTS ON RESPONSES, NOT ON THE PAGE. Each step waits for the request the app actually
 * makes and records its status. A page that has re-rendered pleasantly is not evidence that
 * anything was written, which is the whole premise of this repo.
 *
 *   node harness/rollout.mjs [--keep]      --keep leaves the rows in place for a grader run
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "/Users/admin/CompoundLabs/compound-ops/tools/lib/safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3773";
const DB_CONTAINER = process.env.DESK_DB_CONTAINER || "supabase_db_stack";
const FIXTURE = path.join(ROOT, "fixtures", "NY-benefit-charge-Q3.pdf");
const RECORD = process.argv.includes("--record");
let recorder = null;

const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));

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

console.log("reset");
reset();
step(`documents=${rows("select count(*) from cd_documents")} statements=${rows("select count(*) from cd_statements")}`);

const browser = await launchSafe(puppeteer, { headless: true });
let ok = true;
try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900 });
  await browser.setCookie(...session.cookies);

  const seen = (globalThis.__seen = []);
  page.on("response", (r) => {
    const u = new URL(r.url()).pathname;
    if (u.startsWith("/dashboard/api/") || u.includes("/storage/v1/")) {
      seen.push({ path: u, status: r.status() });
    }
  });

  await page.goto(`${APP}/?view=ledger`, { waitUntil: "networkidle2", timeout: 60000 });
  step("ledger open");

  /* ⛔ THE RECORDING DOES NOT SCROLL AND DOES NOT SELECT TEXT. The task is an upload and a
   * button press, both already in frame on the ledger, so there is nothing to travel to. */
  if (RECORD) {
    fs.mkdirSync(path.join(ROOT, "demo"), { recursive: true });
    recorder = await page.screencast({ path: path.join(ROOT, "demo", "rollout.webm") });
    step("recording");
  }

  const input = await page.waitForSelector("input[type=file]", { timeout: 20000 });
  const confirmed = page.waitForResponse(
    (r) => r.url().includes("/dashboard/api/upload/confirm"),
    { timeout: 60000 },
  );
  await input.uploadFile(FIXTURE);
  step(`put ${path.basename(FIXTURE)} on the file input`);

  const confirmRes = await confirmed;
  const confirmBody = await confirmRes.json().catch(() => ({}));
  step(`confirm -> ${confirmRes.status()} ${JSON.stringify(confirmBody).slice(0, 120)}`);
  if (!confirmRes.ok()) ok = false;

  /* The audit button is addressed by its own text rather than by position: the ledger carries
   * several buttons and an index would silently move the day one is added. */
  const audit = page.waitForResponse((r) => r.url().includes("/dashboard/api/audit/start"), {
    timeout: 60000,
  });
  const pressed = await page.evaluate(() => {
    const b = [...document.querySelectorAll("button")].find(
      (el) => el.textContent.trim().toLowerCase() === "start the audit",
    );
    if (!b) return false;
    b.click();
    return true;
  });
  if (!pressed) throw new Error("no button reads 'Start the audit' on this view");
  step("pressed Start the audit");

  const auditRes = await audit;
  const auditBody = await auditRes.json().catch(() => ({}));
  step(`audit/start -> ${auditRes.status()} ${JSON.stringify(auditBody).slice(0, 120)}`);
  if (!auditRes.ok()) ok = false;

  /* A beat on the finished state so the last frame is not the click. */
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(HERE, "rollout-end.png"), fullPage: false });

  console.log("\nrows afterwards:");
  console.log(`  cd_documents  ${rows("select count(*) from cd_documents")}`);
  console.log(`  cd_statements ${rows("select count(*) from cd_statements")}`);
  console.log(
    `  audit stamped ${rows("select count(*) from cd_documents where audit_started_at is not null")}`,
  );
  console.log(
    `  newest doc    ${rows("select original_name || ' kind=' || kind || ' bytes=' || byte_size from cd_documents order by created_at desc limit 1")}`,
  );
} catch (err) {
  ok = false;
  console.error(`\nFAILED: ${err.message}`);
} finally {
  /* Printed on success AND on failure. On a timeout this list is the whole diagnosis: it says
   * whether the app asked for an upload ticket at all, which separates "the file never reached
   * the handler" from "the handler ran and the server refused". */
  if (recorder) {
    await recorder.stop();
    console.log(`\nrecording: ${path.join(ROOT, "demo", "rollout.webm")}`);
  }
  console.log("\nrequests the app made:");
  if (!globalThis.__seen?.length) console.log("  (none)");
  for (const s of globalThis.__seen ?? []) console.log(`  ${String(s.status).padStart(3)}  ${s.path}`);
  await browser.close();
}

if (!process.argv.includes("--keep")) reset();
process.exit(ok ? 0 : 1);
