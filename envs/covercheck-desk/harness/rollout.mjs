/* One scripted rollout of a browser task, start to finish, against the running console.
 *
 *   node harness/rollout.mjs [--task <id>] [--keep] [--record]
 *
 *   file-the-certificate         put the fixture on the file input and file it
 *   sign-and-approve-the-chase   rewrite the sign-off, save, approve     (the default)
 *   stop-the-approved-chase      kill the approved chase inside its window
 *
 * ⛔ IT ASSERTS ON RESPONSES, NOT ON THE PAGE. Each step waits for the request the app actually
 * makes and records its status. A page that has re-rendered pleasantly is not evidence that
 * anything was written, which is the whole premise of this repo.
 *
 * ⛔ NOTHING HERE SCROLLS BY A NUMBER, WALKS A LIST, OR SELECTS TEXT. Every move names the element
 * it is going to and lets that element's own rect decide, measured in the moment. The chase panel
 * sits below the fold on a 900px viewport, so the draft this rollout is about is brought into
 * frame by `scrollIntoView` on that one article and nothing else is travelled past. The body is
 * replaced through React's own value setter rather than by selecting the textarea's contents,
 * which is both more reliable and the estate's rule for anything a camera could be pointed at.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import puppeteer from "puppeteer-core";
import { launchSafe } from "./safe-chrome.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3764";
const DB_CONTAINER = process.env.DESK_DB_CONTAINER || "supabase_db_stack";
const FIXTURE = path.join(ROOT, "fixtures", "bright-path-renewal-acord25.pdf");

const DRAFT_ID = "00000000-0000-4000-8000-000000009001";
const APPROVED_ID = "00000000-0000-4000-8000-000000009002";
const VENDOR_BRIGHT_PATH = "00000000-0000-4000-8000-000000003001";
const SIGNATURE = "Dolores Whitcomb\nHarbor Ridge Community Management";

const argv = process.argv.slice(2);
const TASK = argv.includes("--task") ? argv[argv.indexOf("--task") + 1] : "sign-and-approve-the-chase";
const RECORD = argv.includes("--record");
const KEEP = argv.includes("--keep");

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

/** Bring ONE named element into frame, by its own rect, or do nothing if it is already there. */
async function bringIntoFrame(page, selector) {
  const moved = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const inFrame = r.top >= 0 && r.bottom <= window.innerHeight;
    if (inFrame) return "already in frame";
    el.scrollIntoView({ block: "center", behavior: "instant" });
    return "brought into frame";
  }, selector);
  if (moved === null) throw new Error(`nothing matches ${selector}`);
  step(`${selector}: ${moved}`);
}

/** Open a chase card by clicking its own header, and wait for the body to be usable. */
async function openChase(page, id) {
  const sel = `#chase-${id}`;
  await page.waitForSelector(sel, { timeout: 20000 });
  await bringIntoFrame(page, sel);
  await page.evaluate((s) => {
    const card = document.querySelector(s);
    if (card.dataset.open !== "true") card.querySelector(".draft-head").click();
  }, sel);
  await page.waitForFunction((s) => document.querySelector(s)?.dataset.open === "true", {}, sel);
  step(`opened ${sel}`);
}

/** Click the one button inside a card whose label reads exactly this. */
async function clickIn(page, sel, label) {
  const hit = await page.evaluate(
    (s, want) => {
      const b = [...document.querySelectorAll(`${s} button`)].find(
        (el) => el.textContent.trim().toLowerCase() === want.toLowerCase(),
      );
      if (!b) return [...document.querySelectorAll(`${s} button`)].map((el) => el.textContent.trim());
      b.click();
      return true;
    },
    sel,
    label,
  );
  if (hit !== true) {
    throw new Error(`no button reads ${JSON.stringify(label)} in ${sel}; it carries ${JSON.stringify(hit)}`);
  }
  step(`pressed ${JSON.stringify(label)}`);
}

/** A response waiter that will not take the process down if the click before it throws.
 *  An unhandled rejection here turns a legible "no button reads X" into a stack trace from
 *  inside puppeteer, which is the diagnosis nobody wants. */
function expectResponse(page, predicate, timeout = 60000) {
  return page.waitForResponse(predicate, { timeout }).then(
    (r) => r,
    (error) => ({ error }),
  );
}

async function settled(waiter) {
  const r = await waiter;
  if (r && r.error) throw r.error;
  return r;
}

/** Wait for a card to offer a control, rather than assuming the click before it has re-rendered. */
async function waitForButton(page, sel, label) {
  await page.waitForFunction(
    (s, want) =>
      [...document.querySelectorAll(`${s} button`)].some(
        (b) => b.textContent.trim().toLowerCase() === want.toLowerCase(),
      ),
    { timeout: 20000 },
    sel,
    label,
  );
}

/** Write into a controlled React field without touching the selection. */
async function setField(page, selector, value) {
  await page.evaluate(
    (sel, v) => {
      const el = document.querySelector(sel);
      if (!el) throw new Error(`no ${sel}`);
      const proto = el instanceof HTMLTextAreaElement
        ? window.HTMLTextAreaElement.prototype
        : el instanceof HTMLSelectElement
          ? window.HTMLSelectElement.prototype
          : window.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(el, v);
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    },
    selector,
    value,
  );
}

const browser = await launchSafe(puppeteer, { headless: true });
let ok = true;
let recorder = null;

console.log(`reset (task: ${TASK})`);
reset();

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
  step("console open");

  if (RECORD) {
    fs.mkdirSync(path.join(ROOT, "demo"), { recursive: true });
    recorder = await page.screencast({ path: path.join(ROOT, "demo", `${TASK}.webm`) });
    step("recording");
  }

  if (TASK === "file-the-certificate") {
    await bringIntoFrame(page, ".bar");
    await page.evaluate(() => {
      const tab = [...document.querySelectorAll('[role="tab"]')].find(
        (t) => t.textContent.trim() === "Upload the PDF",
      );
      if (!tab) throw new Error("no 'Upload the PDF' tab");
      tab.click();
    });
    await page.waitForSelector(".bar select", { timeout: 20000 });

    /* ⛔ THE SELECT DEFAULTS TO THE WRONG VENDOR AND THAT IS NOT A BUG IN THIS SCRIPT. The form
     * picks `vendors[0]`, GET /api/vendors sorts by name, and "Bright Path Pool & Spa Co." sorts
     * before "Bright Path Pool Service". Leaving it alone files the certificate against a real
     * business that is not the one who sent it. */
    const before = await page.$eval(".bar select", (s) => s.selectedOptions[0]?.textContent?.trim());
    await setField(page, ".bar select", VENDOR_BRIGHT_PATH);
    const after = await page.$eval(".bar select", (s) => s.selectedOptions[0]?.textContent?.trim());
    step(`vendor: ${JSON.stringify(before)} -> ${JSON.stringify(after)}`);

    const input = await page.waitForSelector('.bar input[type="file"]', { timeout: 20000 });
    await input.uploadFile(FIXTURE);
    step(`put ${path.basename(FIXTURE)} on the file input`);

    const filed = expectResponse(page, (r) => r.url().includes("/api/cois"), 120000);
    await clickIn(page, ".bar", "Upload and check");
    const res = await settled(filed);
    step(`/api/cois -> ${res.status()} ${JSON.stringify(await res.json().catch(() => ({}))).slice(0, 140)}`);
    if (!res.ok()) ok = false;

    console.log("\nrows afterwards:");
    console.log(`  filed   ${rows("select filename || ' status=' || status || ' bytes=' || byte_size from cc_cois order by uploaded_at desc limit 1")}`);
    console.log(`  vendor  ${rows("select v.name from cc_cois c join cc_vendors v on v.id=c.vendor_id order by c.uploaded_at desc limit 1")}`);
    console.log(`  object  ${rows("select count(*) from storage.objects where bucket_id='covercheck-cois'")}`);
    console.log(`  checks  ${rows("select count(*) from cc_checks")}`);
  } else if (TASK === "sign-and-approve-the-chase") {
    await openChase(page, DRAFT_ID);
    const sel = `#chase-${DRAFT_ID}`;
    await clickIn(page, sel, "Edit");
    await page.waitForSelector(`${sel} textarea`, { timeout: 20000 });

    const body = await page.$eval(`${sel} textarea`, (t) => t.value);
    if (!body.includes("your property manager")) {
      throw new Error("the draft does not carry the placeholder sign-off; the fixture moved");
    }
    await setField(page, `${sel} textarea`, body.replace("your property manager", SIGNATURE));
    step("sign-off replaced");

    const saved = expectResponse(page, (r) => r.url().includes(`/api/chase/${DRAFT_ID}`));
    await clickIn(page, sel, "Save the draft");
    step(`edit -> ${(await settled(saved)).status()}`);

    /* The card leaves editing mode when the save comes back, and Approve only exists after that.
     * Waiting for the control rather than for a duration is the difference between a rollout that
     * works and one that works on a fast machine. */
    await waitForButton(page, sel, "Approve");
    const approved = expectResponse(page, (r) => r.url().includes(`/api/chase/${DRAFT_ID}`));
    await clickIn(page, sel, "Approve");
    const ares = await settled(approved);
    step(`approve -> ${ares.status()} ${JSON.stringify(await ares.json().catch(() => ({}))).slice(0, 140)}`);
    if (!ares.ok()) ok = false;

    console.log("\nrows afterwards:");
    console.log(`  ${rows(`select 'status=' || status || ' edited=' || (edited_at is not null)::text || ' window=' || coalesce(round(extract(epoch from (scheduled_for - approved_at)))::text,'none') || 's sent=' || coalesce(sent_at::text,'never') from cc_chase_messages where id='${DRAFT_ID}'`)}`);
    console.log(`  tail: ${rows(`select right(body, 60) from cc_chase_messages where id='${DRAFT_ID}'`)}`);
    console.log(`  ledger: ${rows(`select string_agg(kind, ', ' order by id) from cc_events where subject_id='${DRAFT_ID}'`)}`);
  } else if (TASK === "stop-the-approved-chase") {
    await openChase(page, APPROVED_ID);
    const sel = `#chase-${APPROVED_ID}`;
    const killed = expectResponse(page, (r) => r.url().includes(`/api/chase/${APPROVED_ID}`));
    await clickIn(page, sel, "Kill it");
    const res = await settled(killed);
    step(`kill -> ${res.status()} ${JSON.stringify(await res.json().catch(() => ({}))).slice(0, 140)}`);
    if (!res.ok()) ok = false;

    console.log("\nrows afterwards:");
    console.log(`  stopped ${rows(`select 'status=' || status || ' killed_at=' || coalesce(killed_at::text,'never') || ' window=' || coalesce(scheduled_for::text,'cleared') from cc_chase_messages where id='${APPROVED_ID}'`)}`);
    console.log(`  other   ${rows(`select 'status=' || status from cc_chase_messages where id='${DRAFT_ID}'`)}`);
    console.log(`  ledger  ${rows(`select string_agg(kind, ', ' order by id) from cc_events where subject_id='${APPROVED_ID}'`)}`);
  } else {
    throw new Error(`unknown task ${JSON.stringify(TASK)}`);
  }

  // A beat on the finished state, so the last frame is not the click.
  await new Promise((r) => setTimeout(r, 1500));
  await page.screenshot({ path: path.join(HERE, `rollout-${TASK}.png`) });
} catch (err) {
  ok = false;
  console.error(`\nFAILED: ${err.message}`);
} finally {
  /* Printed on success AND on failure. On a timeout this list is the whole diagnosis: it says
   * whether the app was asked to do anything at all, which separates "the control was never
   * pressed" from "the route ran and refused". */
  if (recorder) {
    await recorder.stop();
    console.log(`\nrecording: demo/${TASK}.webm`);
  }
  console.log("\nrequests the app made:");
  if (!globalThis.__seen?.length) console.log("  (none)");
  for (const s of globalThis.__seen ?? []) console.log(`  ${String(s.status).padStart(3)}  ${s.path}`);
  await browser.close();
}

if (!KEEP) reset();
process.exit(ok ? 0 : 1);
