/* THE OUTBOUND FIREWALL, AND THE ONE STUB THIS PRODUCT CANNOT RUN WITHOUT.
 *
 * Preloaded into `next start` and into every run of `scripts/mirror-posts.mjs` with
 * NODE_OPTIONS=--import, so it is part of how this environment RUNS Agentwire rather than a
 * change to Agentwire. Nothing in ~/CompoundLabs/agentwire is touched.
 *
 * ⛔ THREE PATHS IN THIS PRODUCT REACH THE NETWORK ON THEIR OWN, and one of them runs inside a
 * route this environment grades:
 *
 *   1. THE HOUSE MAILER RENDERS REMOTELY, AND IT RENDERS BEFORE IT LOOKS FOR A KEY.
 *      src/lib/email-render.ts posts to
 *      https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render, which is the
 *      PRODUCTION project. `POST /api/subscribe` calls confirmEmail() -> renderEmail() ->
 *      that fetch, and only afterwards does sendEmail() find RESEND_API_KEY missing. So
 *      "leave the Resend key unset" does not keep this environment offline, and a plain
 *      refusal of that host turns every subscribe into a 500 whose row is written and whose
 *      page says the send failed. That is not what the product does when it is healthy, and
 *      an environment that can only measure the unhealthy path is measuring the wrong thing.
 *
 *      So that ONE url is STUBBED rather than refused: a deterministic, local, offline
 *      response in the shape renderTemplate() asserts, `{ html, text }`, both non-empty. It
 *      is a test double for a third party, not a copy of the one email template, and nothing
 *      grades its bytes. What it buys is that `POST /api/subscribe` runs its real, healthy
 *      path end to end with no packet leaving this machine.
 *
 *   2. RESEND. src/lib/email.ts POSTs to api.resend.com. RESEND_API_KEY is deliberately
 *      absent, so sendEmail() logs and returns null before it opens a socket, and this
 *      firewall refuses the host as well. Two independent reasons no mail can be sent.
 *
 *   3. THE MIRROR PURGES PRODUCTION'S CACHE. scripts/mirror-posts.mjs has
 *      SITE_URL = 'https://agentwire.thecompound.tech' hardcoded and POSTs
 *      /api/revalidate to it after a successful write. up.sh leaves REVALIDATE_SECRET unset,
 *      which makes the script skip the call and say so; this refuses the host as the second
 *      layer, because a bring-up that quietly poked the live site would be an environment
 *      with a side effect on production.
 *
 * Every other fetch out of the process is checked and anything that is not the local Supabase
 * stack or the app itself is refused before a connection is opened. It fails CLOSED: an
 * unparseable target is refused, not allowed.
 */
const ALLOW = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

const EMAIL_RENDER =
  "https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render";

const original = globalThis.fetch;

/* The double. Deterministic, derived only from what the caller passed, and plainly marked as
 * a stub so nothing can mistake its output for the studio's template. renderTemplate() checks
 * res.ok, out.html and out.text, and nothing else in the product reads the body. */
function stubbedRender(body) {
  let kind = "email";
  let opts = {};
  try {
    const parsed = JSON.parse(body ?? "{}");
    kind = String(parsed.kind ?? "email");
    opts = parsed.opts ?? {};
  } catch {
    /* an unreadable body still gets a valid-shaped answer; the route's own error path is not
       what this stub is here to exercise */
  }
  const heading = String(opts.heading ?? "Agentwire");
  const lines = Array.isArray(opts.body) ? opts.body.map(String) : [];
  const cta = opts.cta && typeof opts.cta === "object" ? opts.cta : null;
  const blocks = Array.isArray(opts.blocks) ? opts.blocks : [];
  const unsub = opts.unsubscribeUrl ? String(opts.unsubscribeUrl) : null;

  const parts = [];
  const textParts = [];
  parts.push(`<h1>${heading}</h1>`);
  textParts.push(heading);
  for (const line of lines) {
    parts.push(`<p>${line}</p>`);
    textParts.push(line);
  }
  for (const b of blocks) {
    if (b && b.type === "para" && b.text) {
      parts.push(`<p>${b.text}</p>`);
      textParts.push(String(b.text));
    } else if (b && b.type === "items" && Array.isArray(b.items)) {
      for (const it of b.items) {
        parts.push(`<p><a href="${it.url}">${it.title}</a> ${it.source ?? ""}</p>`);
        textParts.push(`${it.title} (${it.url}) ${it.source ?? ""}`);
      }
    } else if (b && b.type === "link" && b.url) {
      parts.push(`<p><a href="${b.url}">${b.label ?? b.url}</a></p>`);
      textParts.push(`${b.label ?? b.url} (${b.url})`);
    }
  }
  if (cta && cta.url) {
    parts.push(`<p><a href="${cta.url}">${cta.label ?? "Open"}</a></p>`);
    textParts.push(`${cta.label ?? "Open"} (${cta.url})`);
  }
  if (unsub) {
    parts.push(`<p><a href="${unsub}">Unsubscribe</a></p>`);
    textParts.push(`Unsubscribe (${unsub})`);
  }

  const html =
    `<!doctype html><html lang="en"><body data-stub="agentwire-desk" data-kind="${kind}">` +
    parts.join("") +
    `<p>agentwire-desk offline render stub. Not the studio email template.</p>` +
    `</body></html>`;
  const text =
    textParts.join("\n") +
    "\n\nagentwire-desk offline render stub. Not the studio email template.";

  return new Response(JSON.stringify({ html, text }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

globalThis.fetch = function guardedFetch(input, init) {
  let raw = null;
  try {
    raw =
      typeof input === "string" ? input
      : input instanceof URL ? input.href
      : input && typeof input.url === "string" ? input.url
      : null;
  } catch {
    raw = null;
  }

  if (raw !== null && raw.split("?")[0] === EMAIL_RENDER) {
    const body =
      init && typeof init.body === "string" ? init.body
      : input && typeof input.body === "string" ? input.body
      : null;
    return Promise.resolve(stubbedRender(body));
  }

  let host = null;
  try {
    if (raw !== null) host = new URL(raw).hostname;
  } catch {
    host = null;
  }
  if (host === null || !ALLOW.has(host)) {
    return Promise.reject(
      new Error(
        `agentwire-desk: refused an outbound request to ${host ?? "an unreadable target"}.` +
          " This environment reaches the local Supabase stack and nothing else: no Resend, no" +
          " production revalidate, no remote template render (that one url is stubbed offline).",
      ),
    );
  }
  return original(input, init);
};
