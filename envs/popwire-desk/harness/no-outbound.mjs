/* THE OUTBOUND FIREWALL, AND THE THREE STUBS THIS PRODUCT CANNOT RUN WITHOUT.
 *
 * Preloaded into `next start` and into every run of `scripts/mirror-posts.mjs` with
 * NODE_OPTIONS=--import, so it is part of how this environment RUNS Popwire rather than a
 * change to Popwire. Nothing in ~/CompoundLabs/popwire is touched.
 *
 * ⛔ FOUR PATHS IN THIS PRODUCT REACH THE NETWORK ON THEIR OWN, and three of them run inside
 * something this environment grades:
 *
 *   1. THE HOUSE MAILER RENDERS REMOTELY, AND IT RENDERS BEFORE IT LOOKS FOR A KEY.
 *      src/lib/email-render.ts posts to
 *      https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render, the PRODUCTION
 *      project. `POST /api/subscribe` calls confirmEmail() -> renderEmail() -> that fetch,
 *      and only afterwards does sendEmail() find RESEND_API_KEY missing. So leaving the
 *      Resend key unset does not keep this environment offline, and a plain REFUSAL of that
 *      host turns every subscribe into a 500 whose row is already written and whose form
 *      says the send failed. That is not what the product does when it is healthy, and an
 *      environment that can only measure the unhealthy path measures the wrong thing.
 *
 *   2. THE MIRROR READS THE ACCOUNT'S OWN BLUESKY FEED.
 *      scripts/mirror-posts.mjs GETs
 *      public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=popwire.thecompound.tech
 *      and takes two things off it that appear on the site: the CARD (matched by alt text,
 *      which agent.mjs sets to the topic) and the SOURCE LINK (the self-reply the lane files
 *      under every dispatch, read out of that post's richtext facets). Left to the real
 *      endpoint, this environment's mirror task would be graded on what the live account
 *      posted this morning, which is not reproducible and is exactly what the contract
 *      forbids. So the one url is answered from fixture/bsky-feed.json, a feed of five posts
 *      about a town that does not exist.
 *
 *   3. THE MIRROR RE-HOSTS THE CARD IT FOUND. rehostCard() fetches the fullsize image off
 *      cdn.bsky.app and uploads two webp derivatives into the `popwire` storage bucket. The
 *      image bytes come from fixture/card.png.b64, a 64x80 two-band PNG this environment
 *      generated. Nothing grades its pixels; what is graded is that the row ends up pointing
 *      at the LOCAL bucket, which is the whole of "the bytes that went out are the bytes on
 *      the site".
 *
 *   4. RESEND. src/lib/email.ts POSTs to api.resend.com. RESEND_API_KEY is deliberately
 *      absent, so sendEmail() logs and returns null before it opens a socket, and this
 *      refuses the host as well. Two independent reasons no mail can be sent.
 *
 * Every other fetch out of the process is checked and anything that is not the local
 * Supabase stack or the app itself is refused before a connection is opened. It fails
 * CLOSED: an unparseable target is refused, not allowed.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.join(HERE, "..", "fixture");

const ALLOW = new Set(["127.0.0.1", "localhost", "[::1]", "::1"]);

const EMAIL_RENDER =
  "https://xowekqdsttxwbhfxvusa.supabase.co/functions/v1/email-render";
const BSKY_FEED =
  "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed";
const BSKY_CDN = "cdn.bsky.app";

const original = globalThis.fetch;

/* The mailer double. Deterministic, derived only from what the caller passed, and plainly
 * marked as a stub so nothing can mistake its output for the studio's one template.
 * renderTemplate() checks res.ok, out.html and out.text, and nothing else in the product
 * reads the body. */
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
  const heading = String(opts.heading ?? "Popwire");
  const lines = Array.isArray(opts.body) ? opts.body.map(String) : [];
  const cta = opts.cta && typeof opts.cta === "object" ? opts.cta : null;
  const blocks = Array.isArray(opts.blocks) ? opts.blocks : [];
  const unsub = opts.unsubscribeUrl ? String(opts.unsubscribeUrl) : null;

  const parts = [`<h1>${heading}</h1>`];
  const textParts = [heading];
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
    `<!doctype html><html lang="en"><body data-stub="popwire-desk" data-kind="${kind}">` +
    parts.join("") +
    `<p>popwire-desk offline render stub. Not the studio email template.</p>` +
    `</body></html>`;
  const text =
    textParts.join("\n") + "\n\npopwire-desk offline render stub. Not the studio email template.";

  return new Response(JSON.stringify({ html, text }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

let feedCache = null;
function stubbedFeed() {
  if (feedCache === null) {
    feedCache = fs.readFileSync(path.join(FIXTURE, "bsky-feed.json"), "utf8");
  }
  return new Response(feedCache, {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

let cardCache = null;
function stubbedCard() {
  if (cardCache === null) {
    cardCache = Buffer.from(
      fs.readFileSync(path.join(FIXTURE, "card.png.b64"), "utf8").trim(),
      "base64",
    );
  }
  return new Response(cardCache, {
    status: 200,
    headers: { "content-type": "image/png" },
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

  const bare = raw === null ? null : raw.split("?")[0];

  if (bare === EMAIL_RENDER) {
    const body =
      init && typeof init.body === "string" ? init.body
      : input && typeof input.body === "string" ? input.body
      : null;
    return Promise.resolve(stubbedRender(body));
  }
  if (bare === BSKY_FEED) return Promise.resolve(stubbedFeed());

  let host = null;
  try {
    if (raw !== null) host = new URL(raw).hostname;
  } catch {
    host = null;
  }
  if (host === BSKY_CDN) return Promise.resolve(stubbedCard());

  if (host === null || !ALLOW.has(host)) {
    return Promise.reject(
      new Error(
        `popwire-desk: refused an outbound request to ${host ?? "an unreadable target"}.` +
          " This environment reaches the local Supabase stack and nothing else: no Resend, no" +
          " live Bluesky feed, no remote template render. Those three urls are answered" +
          " offline from envs/popwire-desk/fixture.",
      ),
    );
  }
  return original(input, init);
};
