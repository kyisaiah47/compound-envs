/* ONE HONEST ROLLOUT OF AN API TASK, THROUGH THE PRODUCT'S OWN ROUTES.
 *
 *   node harness/act.mjs <action> [--no-reset]
 *   actions: dismiss  approve-yard  kill-notice  sweep  refusal-probe
 *
 * ⛔ WHY THIS EXISTS RATHER THAN A HAND-WRITTEN INSERT. `adversarial/prove_graders.py` can write
 * the end state of a task directly in SQL, and it does, because that proves the grader accepts a
 * correct end state even on a machine with no product checked out. What it cannot prove is that
 * the end state the ROUTE writes is the one the grader accepts. Those are two different claims,
 * and the gap between them is exactly where a grader is green for the wrong reason: a column the
 * route never sets, a timestamp it stamps differently, an event kind spelled another way. So
 * every API task also gets a real call here, and the prove script runs both when the app is up.
 *
 * ⛔ AND IT ASSERTS ON THE RESPONSE, NOT ON A PAGE. Each action prints the status and the body the
 * route answered. None of these four routes renders anything, so there is nothing to look at.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.dirname(HERE);
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3754";
const DB_CONTAINER = process.env.DESK_DB_CONTAINER || "supabase_db_stack";

const FACTS = JSON.parse(fs.readFileSync(path.join(ROOT, "fixtures", "facts.json"), "utf8"));
const session = JSON.parse(fs.readFileSync(path.join(HERE, "session.json"), "utf8"));
const COOKIE = session.cookies.map((c) => `${c.name}=${c.value}`).join("; ");

function reset() {
  execFileSync("docker", [
    "cp",
    path.join(ROOT, "sql", "02-seed.sql"),
    `${DB_CONTAINER}:/tmp/cw-seed.sql`,
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

async function call(method, route, body) {
  const res = await fetch(`${APP}${route}`, {
    method,
    headers: {
      cookie: COOKIE,
      ...(body ? { "content-type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    redirect: "manual",
  });
  const text = await res.text();
  return { status: res.status, body: text.slice(0, 300) };
}

const t0 = Date.now();
const step = (s) => console.log(`  ${String(Date.now() - t0).padStart(6)}ms  ${s}`);

const ACTIONS = {
  /** Task 2. Close the row raised on the agreement with no readable end date. */
  async dismiss() {
    const r = await call("POST", "/api/queue/kill", { signalId: FACTS.signals.rothbury });
    step(`queue/kill -> ${r.status} ${r.body}`);
    return r.status === 200;
  },

  /** Task 3. Stage the notice on the yard agreement, not on the other Pellworth one. */
  async ["approve-yard"]() {
    const r = await call("POST", "/api/queue/approve", { signalId: FACTS.signals.yard });
    step(`queue/approve -> ${r.status} ${r.body}`);
    return r.status === 200;
  },

  /** Task 4. Kill the staged notice while its window is still open. */
  async ["kill-notice"]() {
    const id = FACTS.notices.ostergaard;
    const r = await call("POST", `/api/notices/${id}/cancel`);
    step(`notices/${id}/cancel -> ${r.status} ${r.body}`);
    return r.status === 200;
  },

  /** Task 5. The outbox sweep. Cron-authed in production; CRON_SECRET is unset here, and the
   *  route's own guard is `if (secret && ...)`, so an unset secret leaves it open. */
  async sweep() {
    const r = await call("GET", "/api/notices/dispatch");
    step(`notices/dispatch -> ${r.status} ${r.body}`);
    return r.status === 200;
  },

  /* ⛔ NOT A TASK. PROOF THAT THE PRODUCT REFUSES, so the dismiss task's premise is measured
   * rather than assumed. The Rothbury row carries no quoted span because its clause could not be
   * read, and `schedule()` throws NoticeRefused on exactly that. If this ever answers 200, task 2
   * is no longer about a refusal and its wording has to change. */
  async ["refusal-probe"]() {
    const r = await call("POST", "/api/queue/approve", { signalId: FACTS.signals.rothbury });
    step(`queue/approve on the unquotable row -> ${r.status} ${r.body}`);
    const refused = r.status === 409 && r.body.includes("no source span");
    const still = rows(
      `select status from cw_signals where id = '${FACTS.signals.rothbury}'`,
    );
    const staged = rows(
      `select count(*) from cw_notices where signal_id = '${FACTS.signals.rothbury}'`,
    );
    step(`the row is still ${still}, notices staged on it: ${staged}`);
    if (!refused) console.error("  the approve route did NOT refuse; task 2's premise has moved");
    return refused && still === "open" && staged === "0";
  },
};

const action = process.argv[2];
if (!ACTIONS[action]) {
  console.error(`unknown action ${action}. one of: ${Object.keys(ACTIONS).join(", ")}`);
  process.exit(2);
}

if (!process.argv.includes("--no-reset")) {
  reset();
  step("reset");
}

const ok = await ACTIONS[action]();

console.log("\nrows afterwards:");
console.log(`  open queue    ${rows("select count(*) from cw_signals where status = 'open'")}`);
console.log(
  `  outbox        ${rows("select coalesce(string_agg(state || ' x' || n, ', '), '(empty)') from (select state, count(*) n from cw_notices group by state) t")}`,
);
console.log(`  events        ${rows("select count(*) from cw_events")}`);

process.exit(ok ? 0 : 1);
