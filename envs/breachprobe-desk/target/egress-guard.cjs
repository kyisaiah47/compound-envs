/**
 * THE EGRESS GUARD. Preloaded into the app server with `NODE_OPTIONS=--require`, never written
 * into the product.
 *
 * ⛔ BREACHPROBE REACHES OUT BY DESIGN, WHICH IS THE WHOLE PROBLEM THIS ENVIRONMENT HAS TO
 * SOLVE. `POST /api/scan` fetches whatever url the caller names and follows redirects; the
 * nightly re-scans every monitor's url; `src/lib/email-render.ts` posts to the production
 * Supabase edge function on every attempted send; `readSession()` and the reconciler call
 * api.stripe.com. A promise in a README that none of that leaves the machine is worth nothing.
 * This is the promise as a mechanism: anything that is not loopback is refused before a socket
 * is opened, and the refusal is printed so the log says exactly what the product tried to reach.
 *
 * It is containment, not a patch to the thing under test. The product's code is byte-identical
 * to the repo (rule 12); what changes is what the machine will carry for it. Every refusal
 * surfaces inside the product as a failed fetch, which is a path the product already has and
 * already handles: `fetchPage()` returns `reachable: false`, `renderEmail()` throws and `send()`
 * returns false, `readSession()` throws. Those are the paths this environment grades.
 *
 * ⛔ AND IT IS THE SECOND LOCK ON THE SPEND RULES. STRIPE_SECRET_KEY, RESEND_API_KEY and every
 * model key are absent from the app's environment, so nothing should ever try. If something
 * does, this stops it at the socket rather than at the invoice.
 */
const ALLOWED_HOSTS = new Set(["127.0.0.1", "localhost", "::1", "[::1]", "0.0.0.0"]);

function hostOf(input) {
  try {
    if (typeof input === "string") return new URL(input).hostname;
    if (input && typeof input.url === "string") return new URL(input.url).hostname;
    if (input && typeof input.href === "string") return new URL(input.href).hostname;
  } catch {
    return null;
  }
  return null;
}

const realFetch = globalThis.fetch;

globalThis.fetch = function guardedFetch(input, init) {
  const host = hostOf(input);
  if (host !== null && !ALLOWED_HOSTS.has(host)) {
    const url = typeof input === "string" ? input : input?.url || input?.href || String(input);
    process.stderr.write(`[egress-guard] refused ${url}\n`);
    // The same shape a DNS failure or a refused connection produces, so every caller in the
    // product takes the path it already has for an unreachable host.
    return Promise.reject(
      Object.assign(new TypeError("fetch failed"), {
        cause: new Error(`breachprobe-desk egress guard: ${host} is not loopback`),
      }),
    );
  }
  return realFetch(input, init);
};
