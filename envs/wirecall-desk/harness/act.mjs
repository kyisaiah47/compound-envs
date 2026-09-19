/* The rollouts that have no control on any page, each one driving the product's own route or
 * its own cron.
 *
 *   node harness/act.mjs settle              the daily tick settles yesterday's slate
 *   node harness/act.mjs pass                POST /api/stripe/webhook, a signed completion
 *   node harness/act.mjs pass-wrong-player   the same route, metadata naming the other device
 *   node harness/act.mjs confirm             GET  /api/subscribe/confirm, the mailed link
 *   node harness/act.mjs confirm-twin        the same route, the near twin's link instead
 *
 * ⛔ THESE ARE ROLLOUTS, NOT FIXTURES. Nothing here writes to the database. Every one asks the
 * running product to do the thing and then exits; the grader reads the rows afterwards and never
 * sees this file's opinion of how it went.
 *
 * ⛔ NOTHING HERE REACHES STRIPE OR A MAIL PROVIDER. The webhook signature is computed locally
 * against the fixture endpoint secret, which is all `stripe.webhooks.constructEvent` checks, and
 * the opt-in token is the product's own HMAC. The app server itself runs behind
 * harness/no-outbound.mjs, which refuses every fetch that is not the local stack.
 *
 * ⛔ TWO OF THESE ARE CHEATS THAT DRIVE THE REAL ROUTE, on purpose. `pass-wrong-player` and
 * `confirm-twin` are not hand written rows: they are the product doing exactly what it is asked
 * and landing the result on the wrong player. `pass-wrong-player` is how the defect in
 * src/app/api/stripe/webhook/route.ts is measured rather than argued.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  APP, ORDER_PAYER, OPTIN_EMAIL, P_OPTIN, P_PAYER, P_DECOY, P_TWIN, TWIN_EMAIL,
  optinToken, stripeSignature,
} from "./identity.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const APP_DIR = process.env.DESK_APP_BUILD_DIR || path.join(HERE, "..", "app");

const say = (s) => console.log(`  ${s}`);

/** The game date the tick would pick on its own. localYMD(now, 'America/New_York'), the same
 *  construction scripts/tick.mjs uses, because a slate is found by game_date and the fixture's
 *  days are laid out in that zone. */
function todayInNewYork() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const get = (t) => parts.find((p) => p.type === t).value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}

async function post(path_, body, headers = {}) {
  const res = await fetch(`${APP}${path_}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
    redirect: "manual",
  });
  return { status: res.status, text: await res.text() };
}

/* ── the tick ───────────────────────────────────────────────────────────────────────────────
 * WireCall's one daily job. It settles the PREVIOUS day and then builds the given one, in that
 * order and for the reason its own header gives: a fresh slate must never be buildable before
 * the one it follows has been closed out. Today's slate already exists in the fixture, so the
 * build half reports "a slate for this day already exists" and does nothing, which is the
 * product's own idempotence and not something this script arranges.
 *
 * It runs the product's script unmodified, from the built copy, with the copy's own .env.local.
 */
async function settle() {
  const date = todayInNewYork();
  const out = execFileSync("node", ["scripts/tick.mjs", "--date", date], {
    cwd: APP_DIR, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
  });
  for (const line of out.trim().split("\n")) say(line);
  if (!/\[settle /.test(out)) throw new Error("the tick printed no settle line");
  if (/"skipped"/.test(out.split("[build")[0])) {
    throw new Error("the tick skipped the settle it was run for");
  }
}

/* ── the Wire Pass ──────────────────────────────────────────────────────────────────────────
 * `checkout.session.completed` for the payer's pending order. The handler reads order_id and
 * player_id out of the event's metadata, which is what /api/checkout wrote when it created the
 * session, marks the order paid and puts the pass on the player.
 */
function completionEvent(orderId, playerId) {
  return JSON.stringify({
    id: "evt_wirecall_desk_pass",
    object: "event",
    type: "checkout.session.completed",
    data: {
      object: {
        object: "checkout.session",
        id: "cs_test_wirecall_desk_not_a_session",
        client_reference_id: orderId,
        metadata: { order_id: orderId, player_id: playerId, product: "wirecall" },
      },
    },
  });
}

async function fireCompletion(orderId, playerId, label) {
  const raw = completionEvent(orderId, playerId);
  const r = await post("/api/stripe/webhook", raw, { "stripe-signature": stripeSignature(raw) });
  say(`POST /api/stripe/webhook ${label} -> ${r.status} ${r.text.slice(0, 120)}`);
  if (r.status !== 200) throw new Error(`the webhook refused: ${r.status} ${r.text.slice(0, 300)}`);
}

const pass = () => fireCompletion(ORDER_PAYER, P_PAYER, "checkout.session.completed");

/* ⛔ THE DEFECT, DRIVEN RATHER THAN ARGUED. The handler never compares the metadata's player_id
 * with the order's own player_id, so this marks the PAYER'S order paid and hands the pass to the
 * OTHER pending device. Both rows read correctly on their own afterwards and the route answers
 * 200. See results.json `defects`. */
const passWrongPlayer = () => fireCompletion(ORDER_PAYER, P_DECOY, "metadata naming the decoy");

/* ── the streak reminder ────────────────────────────────────────────────────────────────────
 * The second leg of the double opt in: the link WireCall mailed, clicked. The route answers a
 * 303 back to the slate with ?optin=on rather than a body, so a clicked link never leaves the
 * reader on an API route.
 */
async function hitConfirm(playerId, email, label) {
  const url = `${APP}/api/subscribe/confirm?t=${encodeURIComponent(optinToken(playerId, email))}`;
  const res = await fetch(url, { redirect: "manual" });
  const to = res.headers.get("location") ?? "";
  say(`GET /api/subscribe/confirm ${label} -> ${res.status} ${to}`);
  if (res.status !== 303) throw new Error(`the confirm did not redirect: ${res.status}`);
  if (/optin=(invalid|error)/.test(to)) throw new Error(`the confirm refused the link: ${to}`);
}

const confirm = () => hitConfirm(P_OPTIN, OPTIN_EMAIL, "the opt-in's own link");
const confirmTwin = () => hitConfirm(P_TWIN, TWIN_EMAIL, "the near twin's link");

const ACTIONS = { settle, pass, "pass-wrong-player": passWrongPlayer, confirm, "confirm-twin": confirmTwin };

const what = process.argv[2];
if (!ACTIONS[what]) {
  console.error(`usage: node harness/act.mjs <${Object.keys(ACTIONS).join("|")}>`);
  process.exit(2);
}
console.log(what);
await ACTIONS[what]();
console.log("done");
