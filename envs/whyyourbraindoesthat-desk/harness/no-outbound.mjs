/* THE OUTBOUND FIREWALL FOR THE APP UNDER TEST. Preloaded into `next start` with
 * NODE_OPTIONS=--import, so it is part of how this environment RUNS the product rather than a
 * change to the product. Nothing in ~/CompoundLabs/whyyourbraindoesthat is touched.
 *
 * ⛔ WHY IT EXISTS HERE, given this product has no mailer, no payment processor and no model
 * call. Two reasons, and neither is a precaution:
 *
 *   1. `@supabase/supabase-js` takes its host from `SUPABASE_URL` at call time, not at build
 *      time. up.sh writes the local url into .env.local, and a stale shell environment, a
 *      leftover .env in the copy, or a hand run of `npm start` from the wrong directory all put
 *      the PRODUCTION project back in that variable. Every one of those turns a rollout into a
 *      write against the live reader list, silently, with a 200 on the way back. This refuses
 *      the connection instead.
 *   2. src/components/Analytics.tsx initialises posthog-js against https://us.i.posthog.com.
 *      That is browser side, so this does not catch it; harness/safe-chrome.mjs aborts it in the
 *      page. Both halves are needed and neither covers the other.
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
      `whyyourbraindoesthat-desk: refused an outbound request to ${host ?? "an unreadable target"}.` +
      " This environment reaches the local Supabase stack and nothing else. A request to" +
      " xowekqdsttxwbhfxvusa.supabase.co here means SUPABASE_URL is pointing at production and" +
      " the reader list about to be written is the live one.";
    return Promise.reject(new Error(why));
  }
  return original(input, init);
};
