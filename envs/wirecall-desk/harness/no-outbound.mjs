/* THE OUTBOUND FIREWALL FOR THE APP UNDER TEST. Preloaded into `next start` with
 * NODE_OPTIONS=--import, so it is part of how this environment RUNS the product rather than a
 * change to the product. Nothing in ~/CompoundLabs/wirecall is touched.
 *
 * ⛔ WHY IT EXISTS, AND IT IS NOT A PRECAUTION. Two paths WireCall carries reach the network on
 * their own, and one of them runs inside a route this environment grades:
 *
 *   1. THE HOUSE MAILER RENDERS REMOTELY. vendor/compound-mail/src/email-render.ts posts the
 *      body to https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render BEFORE it
 *      looks for a Resend key, so "leave RESEND_API_KEY unset" does not stop the request. The
 *      Wire Pass webhook calls sendPassReceipt() after its two writes, inside a try/catch.
 *   2. STRIPE. /api/checkout constructs a Stripe client and calls checkout.sessions.create.
 *      WireCall sits on the SECOND of the two live Stripe secret keys on this machine, the one
 *      OutRip and MatchLine also carry. up.sh sets a placeholder, so the call would 401 rather
 *      than charge anything, but a request that is never made cannot be got wrong.
 *
 * So every fetch out of the app server is checked here and anything that is not the local
 * Supabase stack or the app itself is refused before a connection is opened. A refusal reads
 * exactly like a network failure, which is the shape both call sites already handle: the
 * webhook logs its receipt error and still answers 200 with both writes standing, and checkout
 * answers its own 500 with "Nothing was charged."
 *
 * It fails CLOSED. An unparseable target is refused, not allowed.
 */
const ALLOW = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

const original = globalThis.fetch;

globalThis.fetch = function guardedFetch(input, init) {
  let host = null;
  try {
    const raw =
      typeof input === "string" ? input
      : input instanceof URL ? input.href
      : input && typeof input.url === "string" ? input.url
      : null;
    if (raw !== null) host = new URL(raw).hostname;
  } catch {
    host = null;
  }
  if (host === null || !ALLOW.has(host)) {
    const why =
      `wirecall-desk: refused an outbound request to ${host ?? "an unreadable target"}.` +
      " This environment reaches the local Supabase stack and nothing else: no Stripe, no" +
      " Resend, no remote template render.";
    return Promise.reject(new Error(why));
  }
  return original(input, init);
};
