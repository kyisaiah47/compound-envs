/* Sign in once and freeze the session, so an episode starts on the console rather than at a gate.
 *
 * ⛔ THE GATE'S OWN CONTROLS, ENUMERATED OFF THE RUNNING PAGE ON 2026-09-19, and why none of
 * them is the path here. `GET http://127.0.0.1:3769/?login=1` renders four controls in the
 * dialog: `button "Continue with Google"`, `button "Continue with Microsoft"`, `input[email]`
 * and `button[submit] "Email me a sign-in link"`.
 *
 *   1. The two OAuth buttons are dead on this stack, measured rather than assumed. The local
 *      GoTrue's `GET /auth/v1/settings` reports `"google": false` and `"azure": false` with
 *      `"email": true` alone, and `GET /auth/v1/authorize?provider=google` answers 400 with no
 *      redirect. The auth container carries no GOTRUE_EXTERNAL_GOOGLE_* variable at all.
 *      They would also sign in the WRONG PERSON: the account this environment needs is the
 *      fabricated fixture user `ops@lindmark-freight.example`, uuid ...0f3001, which holds the
 *      wallet, the four keys and the memories. A real Google identity has none of those rows.
 *   2. The email link is the product's real path and it cannot complete here either. It is
 *      `signInWithOtp` with `emailRedirectTo: <origin>/auth/callback` under PKCE, and the
 *      SHARED stack's GoTrue carries `GOTRUE_URI_ALLOW_LIST=https://127.0.0.1:3000`. A link
 *      aimed at 127.0.0.1:3769 is not on that list, so GoTrue sends the browser to the site_url
 *      instead and the code exchange never reaches the app. Widening the list means editing the
 *      shared stack's config and restarting it under every other environment on this machine.
 *
 * So the session is minted with a password grant against the same GoTrue, on a throwaway local
 * user whose password `scripts/up.sh` set a minute earlier. It produces the identical session.
 *
 * ⛔ AND THE COOKIE IS NOT HAND-ROLLED, which is the other half of the design. @supabase/ssr
 * derives the cookie name from the project ref, base64-encodes the session and CHUNKS it across
 * `sb-<ref>-auth-token.0`, `.1` and so on past a size limit. A guess wrong in any of those three
 * produces a browser that looks signed in and a server that renders signed out, and every check
 * here would report success. The session is therefore minted by the same library version the app
 * reads it with (@supabase/ssr 0.12.7, pinned off the product's package-lock), and whatever
 * cookies that library writes are the cookies captured.
 *
 *   node harness/signin.mjs        # writes harness/session.json
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServerClient } from "@supabase/ssr";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const API_URL = process.env.DESK_API_URL || "http://127.0.0.1:54321";
const ANON = process.env.DESK_ANON_KEY;
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3769";
const EMAIL = process.env.DESK_EMAIL || "ops@lindmark-freight.example";
const SECRET = process.env.DESK_PASSWORD || "parserail-fixture-password";
const OUT = path.join(HERE, "session.json");

if (!ANON) {
  console.error("DESK_ANON_KEY is required (read it with `supabase status -o json`)");
  process.exit(1);
}

/** A cookie jar shaped the way @supabase/ssr wants one. It writes; we keep what it wrote. */
const jar = new Map();

const supabase = createServerClient(API_URL, ANON, {
  cookies: {
    getAll: () => [...jar.entries()].map(([name, value]) => ({ name, value })),
    setAll: (list) => {
      for (const { name, value } of list) {
        if (value === "") jar.delete(name);
        else jar.set(name, value);
      }
    },
  },
});

const { data, error } = await supabase.auth.signInWithPassword({ email: EMAIL, password: SECRET });
if (error) {
  console.error(`sign-in failed for ${EMAIL}: ${error.message}`);
  process.exit(1);
}
if (!data.session) {
  console.error("sign-in returned no session");
  process.exit(1);
}

const cookies = [...jar.entries()]
  .filter(([name]) => name.startsWith("sb-"))
  .map(([name, value]) => ({
    name,
    value,
    domain: "127.0.0.1",
    path: "/",
    httpOnly: false,
    secure: false,
    sameSite: "Lax",
  }));

if (!cookies.length) {
  console.error("the library set no sb-* cookie; the session did not stick");
  process.exit(1);
}

/* ⛔ VERIFY BY RELOADING A GATED ROUTE ON THE SERVER, never by "the grant succeeded". A
 * signed-out render of this app is a perfectly valid page, so "the dashboard loaded" proves
 * nothing. /api/billing/autorecharge is cookie-authed, answers 401 with no session, and writes
 * nothing. /dashboard is checked too, because middleware redirects it away when signed out. */
const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
const probe = await fetch(`${APP}/api/billing/autorecharge`, { headers: { cookie: cookieHeader } });
if (probe.status !== 200) {
  console.error(
    `cookies were set but ${APP}/api/billing/autorecharge answered ${probe.status};` +
      " the server still reads signed-out",
  );
  process.exit(1);
}
const gated = await fetch(`${APP}/dashboard/keys`, {
  headers: { cookie: cookieHeader },
  redirect: "manual",
});
if (gated.status !== 200) {
  console.error(`/dashboard/keys answered ${gated.status}; middleware still reads signed-out`);
  process.exit(1);
}

fs.writeFileSync(
  OUT,
  JSON.stringify(
    {
      email: EMAIL,
      userId: data.session.user.id,
      capturedAt: new Date().toISOString(),
      appUrl: APP,
      cookies,
    },
    null,
    2,
  ),
);

console.log(`signed in as ${EMAIL} (${data.session.user.id})`);
console.log(`autorecharge probe ${probe.status}, /dashboard/keys ${gated.status}`);
for (const c of cookies) console.log(`  ${c.name} (${c.value.length} bytes)`);
console.log(`-> ${path.relative(process.cwd(), OUT)}`);
