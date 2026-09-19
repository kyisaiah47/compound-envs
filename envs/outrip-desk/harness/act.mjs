/* The four API rollouts, each one driving the product's own route over HTTP.
 *
 *   node harness/act.mjs tear-dry        POST /api/rip/open      the tenth dry pack
 *   node harness/act.mjs shop-buy        POST /api/shop          spend dust on the catalogue
 *   node harness/act.mjs reverse         POST /api/stripe/webhook  a signed charge.refunded
 *   node harness/act.mjs visit           GET  /out/<domain>      twice, from one client
 *
 * ⛔ THESE ARE ROLLOUTS, NOT FIXTURES. Nothing here writes to the database. Every one of them
 * asks the running product to do the thing and then exits; the grader reads the rows afterwards
 * and never sees this file's opinion of how it went.
 *
 * ⛔ NOTHING HERE REACHES STRIPE. `reverse` signs its own event with the local webhook secret,
 * which is all `stripe.webhooks.constructEvent` checks, and the handler it reaches
 * (`refundOrder`) touches two tables and no network. There is no Stripe key on this machine's
 * path to it and no request leaves the host.
 */
import {
  APP, BUYER_ONE, BUYER_DRY, buyerCookie, stripeSignature,
} from "./identity.mjs";

const ORDER_DRY = "00000000-0000-4000-8000-0000000fa005";
const ORDER_A = "00000000-0000-4000-8000-0000000fa072";
const FENWICK = "fenwick.example";

/* ⛔ A CLIENT ADDRESS, BECAUSE THE DEDUP KEY IS DERIVED FROM ONE. /out/<domain> hashes
 * x-forwarded-for plus the user agent and refuses a second click from the same hash inside
 * thirty minutes. Served by `next start` with no proxy in front of it there is no such header at
 * all, `clientHash` returns null and the dedup is simply off, so the honest rollout supplies the
 * header a proxy would. Both visits below send the SAME one on purpose: the second one is the
 * repeat that must not count. */
const CLIENT = { "x-forwarded-for": "198.51.100.23", "user-agent": "outrip-desk-harness/1" };

const say = (s) => console.log(`  ${s}`);

async function post(path, body, headers = {}) {
  const res = await fetch(`${APP}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
    redirect: "manual",
  });
  const text = await res.text();
  return { status: res.status, text };
}

async function tearDry() {
  // The buyer sitting on nine dry packs opens the tenth. The route rolls it, the ladder builds
  // the gate card, and the pity guarantee has to be visible in the rows afterwards.
  const r = await post("/api/rip/open", { order: ORDER_DRY }, {
    cookie: `outrip_buyer=${buyerCookie(BUYER_DRY)}`,
  });
  say(`POST /api/rip/open -> ${r.status}`);
  if (r.status !== 200) throw new Error(`tear failed: ${r.status} ${r.text.slice(0, 300)}`);
}

async function shopBuy() {
  // Catalogue card 1, the Bot, onto the seat the buyer already holds. Card 2 is better and sold
  // out; card 3 is out of reach. The route decides all of that, not this script.
  const r = await post("/api/shop", { id: 1, domain: FENWICK }, {
    cookie: `outrip_buyer=${buyerCookie(BUYER_ONE)}`,
  });
  say(`POST /api/shop -> ${r.status} ${r.text.slice(0, 120)}`);
  if (r.status !== 200) throw new Error(`shop buy failed: ${r.status} ${r.text.slice(0, 300)}`);
}

async function reverse() {
  /* A charge.refunded for the first Fenwick pack. The event carries no session and therefore no
   * order metadata, which is exactly why the handler resolves it through the payment intent.
   * The signature is computed locally; the raw body is posted byte for byte, because
   * re-serialising it would change the bytes and the signature would stop matching. */
  const event = {
    id: "evt_outrip_desk_reverse",
    object: "event",
    type: "charge.refunded",
    data: { object: { object: "charge", payment_intent: "pi_fixture_fenwick_a", refunded: true } },
  };
  const raw = JSON.stringify(event);
  const r = await post("/api/stripe/webhook", raw, { "stripe-signature": stripeSignature(raw) });
  say(`POST /api/stripe/webhook charge.refunded -> ${r.status} ${r.text.slice(0, 120)}`);
  if (r.status !== 200) throw new Error(`reversal failed: ${r.status} ${r.text.slice(0, 300)}`);
}

async function visit() {
  for (const n of [1, 2]) {
    const res = await fetch(`${APP}/out/${FENWICK}?src=board`, {
      headers: CLIENT,
      redirect: "manual",
    });
    say(`GET /out/${FENWICK} (${n}) -> ${res.status} ${res.headers.get("location") ?? ""}`);
    if (res.status !== 302) throw new Error(`visit ${n} did not redirect: ${res.status}`);
  }
}

const ACTIONS = { "tear-dry": tearDry, "shop-buy": shopBuy, reverse, visit };

const what = process.argv[2];
if (!ACTIONS[what]) {
  console.error(`usage: node harness/act.mjs <${Object.keys(ACTIONS).join("|")}>`);
  process.exit(2);
}
console.log(what);
await ACTIONS[what]();
console.log("done");
