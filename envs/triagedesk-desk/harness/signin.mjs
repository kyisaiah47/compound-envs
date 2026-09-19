/* Sign in once and freeze the session, so an episode starts on the console rather than at a gate.
 *
 * ⛔ THE GATE'S OWN CONTROL, READ OFF THE RUNNING PAGE, and why it is not the path here.
 * TriageDesk has no passwords. `components/LandingAuth.tsx` is the ONE sign-in surface and it
 * calls `supabase.auth.signInWithOtp({ email, options: { emailRedirectTo:
 * `${origin}/auth/callback?next=/` } })`. There is no password field and no OAuth button.
 *
 *   1. The magic link cannot complete on this stack. It is PKCE, and the SHARED stack's GoTrue
 *      carries a fixed `GOTRUE_URI_ALLOW_LIST`. A link aimed at 127.0.0.1:3751 is not on it, so
 *      GoTrue redirects to the site_url and `/auth/callback` never sees the code. Widening the
 *      list means editing the shared stack's config and restarting it under every other
 *      environment on this machine.
 *   2. It would also sign in the WRONG PERSON. The account this environment needs is the
 *      fabricated fixture user `desk@harrowgate-tools.example`, uuid ...2b001, which owns the
 *      queue, the ledger and the active subscription. A real mailbox owns none of it.
 *
 * So the session is minted with a password grant against the same GoTrue, on the fixture user
 * whose password `scripts/up.sh` set a minute earlier. It produces the identical session.
 *
 * ⛔ AND THE COOKIE IS NOT HAND-ROLLED. @supabase/ssr derives the cookie name from the project
 * ref, base64-encodes the session and CHUNKS it across `sb-<ref>-auth-token.0`, `.1` and so on
 * past a size limit. A guess wrong in any of those three produces a browser that looks signed in
 * and a server that renders signed out, and every check here would report success. The session is
 * therefore minted by the same library version the app reads it with (@supabase/ssr 0.12.7,
 * pinned off the product's own package-lock), and whatever cookies that library writes are the
 * cookies captured.
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
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3751";
const EMAIL = process.env.DESK_EMAIL || "desk@harrowgate-tools.example";
const SECRET = process.env.DESK_PASSWORD || "triagedesk-fixture-password";
const OUT = path.join(HERE, "session.json");

if (!ANON) {
  console.error("DESK_ANON_KEY is required (read it with `supabase status -o json`)");
  process.exit(1);
}

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

/* ⛔ VERIFY ON THE SERVER, never by "the grant succeeded". A signed-out render of this app is a
 * perfectly valid page, so "the console loaded" proves nothing: `/` renders the generated DEMO
 * BOOK to anyone without a session and the two books look alike at a glance.
 *
 * Two probes, and neither writes anything:
 *   · `/api/queue/<any id>` with no `action` in the body. The route reads the session FIRST and
 *     answers 401 when there is none, 403 for the shared demo email, and only then reaches the
 *     action check and answers 400. So 400 is proof of a real, non-demo session, and nothing is
 *     written on any of those branches.
 *   · the console itself, asserted on a customer this fixture owns rather than on a 200. The
 *     demo book is Northwind's, and it contains no Vane.
 */
const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
const probe = await fetch(`${APP}/api/queue/00000000-0000-4000-8000-00000002e001`, {
  method: "POST",
  headers: { cookie: cookieHeader, "content-type": "application/json" },
  body: JSON.stringify({}),
});
if (probe.status !== 400) {
  console.error(
    `cookies were set but ${APP}/api/queue/... answered ${probe.status} ` +
      `(400 = signed in, 401 = the server still reads signed out, 403 = read as the demo account)`,
  );
  process.exit(1);
}

const page = await fetch(`${APP}/`, { headers: { cookie: cookieHeader } });
const html = await page.text();
if (!html.includes("Marguerite Vane")) {
  console.error(
    "the console rendered without a customer this fixture owns; it is the generated demo book",
  );
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
console.log(`queue probe ${probe.status}, console rendered this fixture's own book`);
for (const c of cookies) console.log(`  ${c.name} (${c.value.length} bytes)`);
console.log(`-> ${path.relative(process.cwd(), OUT)}`);
