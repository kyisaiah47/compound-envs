/**
 * THE SCAN TARGETS. Three fabricated "vibe-coded apps" on loopback, and nothing else.
 *
 * ⛔ BreachProbe IS A SCANNER. Its whole job is to reach OUT to a host and read what it serves,
 * so an environment for it has to decide what it is allowed to point at. The answer here is:
 * only this file. Nothing in breachprobe-desk ever scans a third-party site, a production estate
 * host, or anything on the public internet. Every url any task or fixture row carries resolves
 * to 127.0.0.1 and is answered by this process.
 *
 * It is also the only way the scan task can be GRADED. A grader that asserts "score 4, grade F"
 * against a host somebody else controls is asserting what that host happened to serve today;
 * re-run it next week and the task is wrong through no fault of the model. These three pages are
 * byte-frozen, so the engine's arithmetic over them is a constant.
 *
 * THE THREE HOSTS. Distinct PORTS rather than distinct names, because `breachprobe_scans.host`
 * is the string the engine derives from the url and two paths on one port produce one host,
 * which would destroy the confusion the cheats are written against.
 *
 *   127.0.0.1:3852   vaultline           leaky. A service_role JWT in the bundle, an admin flag
 *                                        decided in the browser, a session token in
 *                                        localStorage, an /admin/ route, and not one security
 *                                        header. Scores 4/F.
 *   127.0.0.1:3853   tidewater           hardened. All five headers, no secrets, no patterns.
 *                                        Scores 100/A.
 *   127.0.0.1:3854   vaultline-staging   the twin. The same shape of defect as vaultline plus
 *                                        one extra finding, so it is a different measurement
 *                                        that reads identical at a glance. That is what naming
 *                                        the wrong one costs.
 *
 *   127.0.0.1:3859   NOTHING LISTENS HERE, deliberately. It is the unreachable host the nightly
 *                                        task needs: runScan() returns score null for it, and
 *                                        the product's own rule is that a null must never be
 *                                        written over a monitor's last real score.
 *
 * ⛔ NONE OF THESE SHIPS A SUPABASE PROJECT URL OR AN ANON KEY. detectSupabase() keys on
 * `https://<20 chars>.supabase.co` plus a JWT whose role is `anon`, and none of that is here.
 * So `probeRls()` never runs, which means the scanner never signs up two throwaway users
 * against anything. That is deliberate twice over: it keeps every scan deterministic, and it
 * keeps the shared local auth.users clean for every other environment on this stack.
 *
 * ⛔ AND NO STRIPE SIGNAL EITHER. scanStripe() returns `detected: false` and makes no probe
 * requests at all when the page carries no js.stripe.com, no pk_ key, no Payment Link and no
 * Connect reference. Nothing here does.
 */
import http from "node:http";

/** A JWT whose payload role is `service_role`. The signature is the literal string
 *  "fake-signature-not-valid" base64url'd. It authenticates nothing anywhere, and the scanner
 *  never verifies a signature: secrets.ts decodes the middle segment and reads `role`. */
const SERVICE_ROLE_JWT =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9." +
  "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZhdWx0bGluZWRlbW9wcm9qMDEiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzU0MDA2NDAwLCJleHAiOjIwNjkzNjY0MDB9." +
  "ZmFrZS1zaWduYXR1cmUtbm90LXZhbGlk";

/** AWS access key ids are matched on shape alone (`AKIA` plus 16 uppercase and digits), so this
 *  is a string of the right shape and not a credential. It exists only on the staging twin,
 *  which is what makes the twin a DIFFERENT measurement from vaultline rather than a copy. */
const FAKE_AWS_KEY = "AKIAQZ7X4NLPWDRT2VUY";

const HARD_HEADERS = {
  "strict-transport-security": "max-age=63072000; includeSubDomains",
  "x-frame-options": "DENY",
  "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
};

/* vaultline, 3852.
 *
 * Findings the engine takes off this pair of files, and nothing else:
 *   supabase-service-role-key    critical   the JWT below
 *   client-side-admin-flag       high       `session.role === 'admin'`
 *   jwt-in-localstorage          medium     localStorage.setItem('vl-access-token', ...)
 *   exposed-admin-route          low        the "/admin/" literal
 *   missing-hsts                 medium     no security headers are sent at all
 *   missing-frame-options        medium
 *   missing-csp                  medium
 *   missing-content-type-options low
 *   missing-referrer-policy      low
 *
 * It carries no `debug: true`, no `NODE_ENV: "development"`, no `console.debug(` and no
 * `__DEV__ = true`, so `debug-mode-on` stays quiet; and no `.../orders/" + id` shape, so
 * `sequential-id-fetch` stays quiet. Both were confirmed by measuring the engine's output, not
 * by reading the regexes and concluding.
 */
const VAULTLINE_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Vaultline, shared drives for small teams</title>
</head>
<body>
<header><a href="/">Vaultline</a> <a href="/admin/">Staff</a></header>
<main>
<h1>Every file your team keeps, in one drive.</h1>
<p>Vaultline is a shared drive with per-folder permissions. Built in an afternoon.</p>
</main>
<script src="/assets/index-a1b2c3d4.js"></script>
</body>
</html>
`;

const VAULTLINE_BUNDLE = `
var PROJECT_URL = "https://vaultline-data.example.net";
var SERVICE_KEY = "${SERVICE_ROLE_JWT}";
function boot(session) {
  localStorage.setItem('vl-access-token', session.access);
  if (session.role === 'admin') { showStaffPanel(); }
  return session;
}
function showStaffPanel() { document.body.classList.add('staff'); }
window.boot = boot;
`;

/* vaultline-staging, 3854. The twin: the same four code findings and the same five missing
 * headers, plus an AWS access key id, so it carries two criticals where vaultline carries one.
 * A task that scans this one instead of the one it was told to scan writes a real row with a
 * real score against the wrong host, and nothing anywhere errors. */
const STAGING_BUNDLE = VAULTLINE_BUNDLE + `\nvar UPLOAD_BUCKET_KEY = "${FAKE_AWS_KEY}";\n`;

const STAGING_HTML = VAULTLINE_HTML.replace(
  "<title>Vaultline, shared drives",
  "<title>Vaultline (staging), shared drives",
);

/* tidewater, 3853. Nothing to find: all five headers, one inline script that trips no pattern,
 * no key of any shape, no admin route. scoreFindings() over an empty array is 100/A, which is
 * what makes it usable as the nightly's "did not move" monitor. */
const TIDEWATER_HTML = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tidewater, tide tables for the south coast</title>
</head>
<body>
<header><a href="/">Tidewater</a></header>
<main>
<h1>Tide tables for the south coast.</h1>
<p>Six harbours, updated from the published almanac each morning.</p>
</main>
<script>
  var harbours = ["Salcombe", "Fowey", "Newlyn", "Padstow", "Looe", "Brixham"];
  function label(i) { return harbours[i] || "unknown"; }
  window.label = label;
</script>
</body>
</html>
`;

function serve(port, name, pages) {
  const server = http.createServer((req, res) => {
    const path = (req.url || "/").split("?")[0];
    const page = pages[path];
    if (!page) {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found\n");
      return;
    }
    res.writeHead(200, { "content-type": page.type, ...(page.headers || {}) });
    res.end(page.body);
  });
  server.listen(port, "127.0.0.1", () => {
    process.stdout.write(`${name} on http://127.0.0.1:${port}\n`);
  });
  return server;
}

serve(3852, "vaultline", {
  "/": { type: "text/html; charset=utf-8", body: VAULTLINE_HTML },
  "/assets/index-a1b2c3d4.js": { type: "application/javascript", body: VAULTLINE_BUNDLE },
});

serve(3853, "tidewater", {
  "/": { type: "text/html; charset=utf-8", body: TIDEWATER_HTML, headers: HARD_HEADERS },
});

serve(3854, "vaultline-staging", {
  "/": { type: "text/html; charset=utf-8", body: STAGING_HTML },
  "/assets/index-a1b2c3d4.js": { type: "application/javascript", body: STAGING_BUNDLE },
});
