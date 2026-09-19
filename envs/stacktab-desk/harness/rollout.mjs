/* The honest rollout for each task. It drives the REAL running product, never the database.
 *
 *   node rollout.mjs <task-id>
 *
 * ⛔ THE PAGE CARRIES TWO EMAIL FORMS AND ONLY ONE OF THEM IS THIS PRODUCT'S (rule 7).
 * The right rail holds the price watch, which posts to this app's own /api/watch. The footer
 * holds the studio list capture, which posts CROSS-ORIGIN to
 * https://thecompound.tech/api/list/subscribe, a live production endpoint that runs a real double
 * opt-in and sends real mail. `input[type=email]` matches both, and the second one is above the
 * first in the DOM on some viewports. So the rollout addresses the control by its own id,
 * `#st-watch-email`, and submits ITS OWN form element rather than clicking the page's first
 * button. It also asserts, from inside the page, that the request it made went to /api/watch.
 *
 * ⛔ IT SUBMITS ONCE. Two submissions of the whole-catalogue form write two rows, because
 * `stacktab_price_watch_unique` is not `nulls not distinct` and the watch route's upsert
 * therefore never finds a conflict on a null service_slug. See README, defect 2. A rollout that
 * retried on a slow response would fail its own task.
 */
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { launchSafe } from "./safe-chrome.mjs";
import puppeteer from "puppeteer";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3318";

/* The people in the fixture's prompts. Addresses are invented, on .example domains. */
export const NEW_WATCHER = "Marisol.Vance@Harrowgate-Tools.example";
export const SCOPED_WATCHER = "ingrid.solberg@calderwood-ai.example";
export const SCOPED_SERVICE = "neon";
/* She is already on the whole-catalogue watch. The repeat merges onto her row, which is what
 * migration stacktab_price_watch_nulls_not_distinct made true on 2026-09-19; before it the same
 * call wrote a second row. Typed with capitals and a trailing space on purpose: the merge has to
 * land through the route's own trim and lowercase. */
export const RETURNING_WATCHER = "Rhoda.Pemberton@Ashcombe-Labs.example ";

async function post(body) {
  const res = await fetch(`${APP}/api/watch`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok || !json.ok) throw new Error(`POST /api/watch -> ${res.status} ${JSON.stringify(json)}`);
  return json;
}

/** Fill the price watch in the right rail and submit it once. */
async function watchFromThePage() {
  const browser = await launchSafe(puppeteer);
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 1200 });
    await page.goto(`${APP}/`, { waitUntil: "networkidle2", timeout: 60000 });

    await page.waitForSelector("#st-watch-email", { timeout: 20000 });

    // Record where the page's own fetch went, so the assertion is about the request that
    // happened rather than about a toast.
    const posted = [];
    page.on("request", (r) => {
      if (r.method() === "POST") posted.push(r.url());
    });

    await page.type("#st-watch-email", NEW_WATCHER);
    await page.evaluate(() => {
      const input = document.querySelector("#st-watch-email");
      const form = input.closest("form");
      form.querySelector('button[type="submit"]').click();
    });

    // The form is replaced by its confirmation only when the route answered ok. An error leaves
    // the form standing with a p.err beside it, so this times out rather than passing quietly.
    await page.waitForSelector(".watch p.ok", { timeout: 20000 });
    const said = await page.$eval(".watch p.ok", (el) => el.textContent.trim());

    const foreign = posted.filter((u) => !u.startsWith(APP));
    if (foreign.length) throw new Error(`the page posted off-origin: ${foreign.join(", ")}`);
    const ours = posted.filter((u) => u.endsWith("/api/watch"));
    if (ours.length !== 1) throw new Error(`expected one POST to /api/watch, saw ${posted.length}: ${posted.join(", ")}`);

    console.log(`submitted once, ${ours[0]}`);
    console.log(`the page said: ${said}`);
  } finally {
    await browser.close();
  }
}

/** Run the nightly pass. Same entry point the launchd job runs: `node refresh.mjs`. */
function nightlyRefresh() {
  return new Promise((resolve, reject) => {
    const child = spawn("node", ["refresh.mjs"], {
      cwd: path.join(HERE, "..", "engine"),
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    child.stdout.on("data", (b) => (out += b));
    child.stderr.on("data", (b) => (out += b));
    child.on("close", (code) => {
      process.stdout.write(out);
      code === 0 ? resolve() : reject(new Error(`refresh.mjs exited ${code}`));
    });
  });
}

const TASKS = {
  "watch-the-catalogue-from-the-page": watchFromThePage,
  "watch-one-service-only": () => post({ email: SCOPED_WATCHER, service: SCOPED_SERVICE }),
  "keep-the-returning-watcher": () => post({ email: RETURNING_WATCHER }),
  "run-the-nightly-recheck": nightlyRefresh,
};

const id = process.argv[2];
if (!TASKS[id]) {
  console.error(`unknown task ${id}. one of: ${Object.keys(TASKS).join(", ")}`);
  process.exit(2);
}
await TASKS[id]();
console.log(`rollout ok: ${id}`);
