/* Who the browser is, and how a webhook proves it came from the payment processor.
 *
 * ⛔ OUTRIP HAS NO ACCOUNTS, SO THERE IS NO SIGN-IN TO CAPTURE. Every other environment on this
 * stack opens a session against GoTrue and stores the tokens. outrip has none: a buyer is an
 * opaque uuid in a cookie signed with HMAC-SHA256, minted silently at checkout, and the only way
 * back in is a link mailed to the address Stripe collected. So the harness mints the cookie the
 * product's own three writers mint (/api/checkout, /api/claim, /api/recover/open), using the
 * same secret and the same construction, rather than driving a form that does not exist.
 *
 * ⛔ STRIPE_SECRET_KEY IS NOT A STRIPE KEY HERE AND NOTHING IN THIS FILE TALKS TO STRIPE. The
 * product uses that variable as a signing secret for four unrelated things: the buyer cookie,
 * the pending-order cookie, the recovery token and the click hash. up.sh sets it to a fixture
 * string. The webhook signature below is Stripe's documented scheme computed locally against
 * STRIPE_WEBHOOK_SECRET, which is likewise just an HMAC key: `constructEvent` verifies bytes and
 * makes no network call, so a reversal can be driven end to end offline and for free.
 */
import { createHmac } from "node:crypto";

export const SIGNING_SECRET =
  process.env.DESK_STRIPE_SECRET || "outrip-desk-fixture-hmac-secret-not-a-stripe-key";
export const WEBHOOK_SECRET =
  process.env.DESK_STRIPE_WEBHOOK_SECRET || "whsec_outrip_desk_fixture";

export const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3328";

const b64url = (buf) => buf.toString("base64url");
const sign = (payload) => b64url(createHmac("sha256", SIGNING_SECRET).update(payload).digest());

/** buyerCookieValue(), src/lib/buyer.ts: the id, a dot, and the signature over `buyer:<id>`. */
export function buyerCookie(id) {
  return `${id}.${sign(`buyer:${id}`)}`;
}

/** pendingCookieValue(), src/lib/orders.ts. The only way back to a pack that was paid for and
 *  never opened, written before the buyer ever leaves for the payment page. */
export function pendingCookie(orderId) {
  return `${orderId}.${sign(`pending:${orderId}`)}`;
}

/** recoveryToken(), src/lib/buyer.ts. Thirty minutes, signature checked before expiry. */
export function recoveryToken(buyerId, ttlMs = 30 * 60_000) {
  const exp = Date.now() + ttlMs;
  return `${buyerId}.${exp}.${sign(`recover:${buyerId}:${exp}`)}`;
}

/** The `Stripe-Signature` header for a raw body. Scheme v1, the documented construction:
 *  HMAC-SHA256 over `${timestamp}.${payload}`, hex. Local crypto only. */
export function stripeSignature(raw, at = Math.floor(Date.now() / 1000)) {
  const mac = createHmac("sha256", WEBHOOK_SECRET).update(`${at}.${raw}`).digest("hex");
  return `t=${at},v1=${mac}`;
}

export const BUYER_ONE = "00000000-0000-4000-8000-0000000f1001";
export const BUYER_TWO = "00000000-0000-4000-8000-0000000f1002";
export const BUYER_DRY = "00000000-0000-4000-8000-0000000f1003";
