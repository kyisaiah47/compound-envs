/* Sign in once and freeze the session, so an episode starts on the console rather than at a gate.
 *
 * ⛔ THE GATE'S OWN CONTROL, READ OFF THE RUNNING PAGE, and why it is not the path here.
 * LeadGrade's sign-in is ONE control: `components/console/SignIn.tsx` calls
 * `supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: `${location.origin}/auth/callback` } })`.
 * There is no password field, no OAuth button and no other form on the page.
 *
 *   1. The magic link cannot complete on this stack. It is PKCE, and the SHARED stack's GoTrue
 *      carries `GOTRUE_URI_ALLOW_LIST=https://127.0.0.1:3000`. A link aimed at 127.0.0.1:3753 is
 *      not on that list, so GoTrue redirects to the site_url instead and `/auth/callback` never
 *      sees the code. Widening the list means editing the shared stack's config and restarting it
 *      under every other environment on this machine.
 *   2. It would also sign in the WRONG PERSON. The account this environment needs is the
 *      fabricated fixture user `ops@harlow-instruments.example`, uuid ...0ff001, which holds the
 *      nine leads, the five write-backs and the active subscription. A real mailbox has none.
 *
 * So the session is minted with a password grant against the same GoTrue, on a throwaway local
 * user whose password `scripts/up.sh` set a minute earlier. It produces the identical session.
 *
 * ⛔ AND THE COOKIE IS NOT HAND-ROLLED. @supabase/ssr derives the cookie name from the project
 * ref, base64-encodes the session and CHUNKS it across `sb-<ref>-auth-token.0`, `.1` and so on
 * past a size limit. A guess wrong in any of those three produces a browser that looks signed in
 * and a server that renders signed out, and every check here would report success. The session is
 * therefore minted by the same library version the app reads it with (@supabase/ssr 0.12.7,
 * pinned off the product's package-lock), and whatever cookies that library writes are the
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
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3753";
const EMAIL = process.env.DESK_EMAIL || "ops@harlow-instruments.example";
const SECRET = process.env.DESK_PASSWORD || "leadgrade-fixture-password";
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
 * perfectly valid page, so "the console loaded" proves nothing: `/` renders the DEMO BOOK to
 * anyone without a session and the two books look alike at a glance.
 *
 * Two probes, and neither writes anything:
 *   · `/api/queue/<a lead id>` with no action in the body. The route reads the session FIRST and
 *     answers 401 when there is none; with a session it falls through to the action check and
 *     answers 400. So 400 is proof of a session, and nothing is written on either branch.
 *   · the console itself, asserted on the tenant's own name rather than on a 200.
 */
const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
const probe = await fetch(`${APP}/api/queue/11111111-0000-4000-8000-000000000006`, {
  method: "POST",
  headers: { cookie: cookieHeader, "content-type": "application/json" },
  body: JSON.stringify({}),
});
if (probe.status !== 400) {
  console.error(
    `cookies were set but ${APP}/api/queue/... answered ${probe.status} (400 = signed in, ` +
      `401 = the server still reads signed out, 402 = signed in with no active plan)`,
  );
  process.exit(1);
}

const page = await fetch(`${APP}/`, { headers: { cookie: cookieHeader } });
const html = await page.text();
if (!html.includes("Harlow Instruments")) {
  console.error("the console rendered without the tenant's own HubSpot label; it is the demo book");
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
console.log(`queue probe ${probe.status}, console rendered the tenant book`);
for (const c of cookies) console.log(`  ${c.name} (${c.value.length} bytes)`);
console.log(`-> ${path.relative(process.cwd(), OUT)}`);
