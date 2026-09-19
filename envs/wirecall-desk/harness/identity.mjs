/* Who the browser is, how a webhook proves it came from the payment processor, and what a
 * confirmation link in an email looks like.
 *
 * ⛔ WIRECALL HAS NO ACCOUNTS, SO THERE IS NO SIGN-IN TO CAPTURE. There is no signup form, no
 * password, no auth.users row and no GoTrue call anywhere in the product. A player is an opaque
 * uuid the server mints on first contact and hands back inside a signed device key that the
 * browser keeps in localStorage under `wirecall_device`, and sends as `x-device-key` or in the
 * body on every write (src/lib/device.ts). So the harness mints the key the product's own
 * `deviceKeyValue()` mints, using the same secret and the same construction, and seeds it into
 * localStorage before the console loads.
 *
 * ⛔ STRIPE_SECRET_KEY IS NOT A STRIPE KEY HERE AND NOTHING IN THIS FILE TALKS TO STRIPE.
 * WireCall uses that variable as an HMAC secret for two unrelated things: the device key and the
 * opt-in token. scripts/up.sh sets it to a fixture string. The webhook signature below is
 * Stripe's documented v1 scheme computed locally against STRIPE_WEBHOOK_SECRET, which is
 * likewise just an HMAC key: `constructEvent` verifies bytes and makes no network call, so the
 * Wire Pass task runs end to end offline and for free.
 */
import { createHmac, timingSafeEqual } from "node:crypto";

export const SIGNING_SECRET =
  process.env.DESK_STRIPE_SECRET || "wirecall-desk-fixture-hmac-secret-not-a-stripe-key";
export const WEBHOOK_SECRET =
  process.env.DESK_STRIPE_WEBHOOK_SECRET || "whsec_wirecall_desk_fixture";

export const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3374";

const sign = (payload) =>
  createHmac("sha256", SIGNING_SECRET).update(payload).digest("base64url");

/** deviceKeyValue(), src/lib/device.ts: the id, a dot, and the signature over `device:<id>`. */
export function deviceKey(id) {
  return `${id}.${sign(`device:${id}`)}`;
}

/** optinToken(), src/lib/optin.ts. Four dot separated parts, 24 hour TTL, signature over
 *  `optin:<playerId>:<email>:<exp>`. This is the link WireCall puts in the confirmation mail. */
export function optinToken(playerId, email, ttlMs = 24 * 60 * 60_000) {
  const exp = Date.now() + ttlMs;
  const payload = `optin:${playerId}:${email}:${exp}`;
  return `${playerId}.${Buffer.from(email).toString("base64url")}.${exp}.${sign(payload)}`;
}

/** The `Stripe-Signature` header for a raw body. Scheme v1, the documented construction:
 *  HMAC-SHA256 over `${timestamp}.${payload}`, hex. Local crypto only. */
export function stripeSignature(raw, at = Math.floor(Date.now() / 1000)) {
  const mac = createHmac("sha256", WEBHOOK_SECRET).update(`${at}.${raw}`).digest("hex");
  return `t=${at},v1=${mac}`;
}

/** A self check that the construction above is the product's, not a lookalike. Called by act.mjs
 *  before it uses a key: a device key that does not verify does not error, it silently mints a
 *  NEW player, and the whole rollout then reads as a success against the wrong row. */
export function deviceKeyVerifies(id) {
  const value = deviceKey(id);
  const cut = value.lastIndexOf(".");
  const want = sign(`device:${value.slice(0, cut)}`);
  const got = value.slice(cut + 1);
  return got.length === want.length && timingSafeEqual(Buffer.from(got), Buffer.from(want));
}

export const P_CALLER = "00000000-0000-4000-8000-0000000f5001";
export const P_RIVAL = "00000000-0000-4000-8000-0000000f5002";
export const P_PAYER = "00000000-0000-4000-8000-0000000f5003";
export const P_DECOY = "00000000-0000-4000-8000-0000000f5004";
export const P_OPTIN = "00000000-0000-4000-8000-0000000f5005";
export const P_TWIN = "00000000-0000-4000-8000-0000000f5006";

export const ORDER_PAYER = "00000000-0000-4000-8000-0000000f5601";
export const ORDER_DECOY = "00000000-0000-4000-8000-0000000f5602";
export const PAYER_EMAIL = "wren.calloway@harbourpost.example";
export const DECOY_EMAIL = "wren.callowaye@harbourpost.example";

export const OPTIN_EMAIL = "imogen.trass@northquay.example";
export const TWIN_EMAIL = "imogen.trasse@northquay.example";
