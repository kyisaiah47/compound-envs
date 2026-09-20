/* Sign in once and freeze the session, so a run starts on the console rather than at a gate.
 *
 * THE GATE'S OWN CONTROL, READ OFF THE RUNNING PAGE. FetchDue's sign-in is a real password form:
 * `src/components/Auth.tsx` calls `supabase.auth.signInWithPassword({ email, password })` on
 * submit, and the same component also carries a SIGN UP branch and an OAuth button. There is no
 * middleware in this repo at all, so nothing refreshes the session between requests.
 *
 * The session is minted with the same password grant against the same GoTrue, on the fabricated
 * fixture user `desk@harrowgate-joinery.example`, uuid ...2c001, whose password scripts/up.sh set
 * a minute earlier. It produces the identical session the form produces.
 *
 * THE COOKIE IS NOT HAND ROLLED. @supabase/ssr derives the cookie name from the project ref,
 * base64 encodes the session and CHUNKS it across `sb-<ref>-auth-token.0`, `.1` and so on past a
 * size limit. A guess wrong in any of those three produces a browser that looks signed in and a
 * server that renders signed out, and every check here would report success. So the session is
 * minted by the same library version the app reads it with (@supabase/ssr 0.12.7, pinned off the
 * product's own package-lock), and whatever cookies that library writes are the cookies captured.
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
const APP = process.env.DESK_APP_URL || "http://127.0.0.1:3757";
const EMAIL = process.env.DESK_EMAIL || "desk@harrowgate-joinery.example";
const SECRET = process.env.DESK_PASSWORD || "fetchdue-fixture-password";
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
    name, value, domain: "127.0.0.1", path: "/", httpOnly: false, secure: false, sameSite: "Lax",
  }));

if (!cookies.length) {
  console.error("the library set no sb-* cookie; the session did not stick");
  process.exit(1);
}

/* VERIFY ON THE SERVER, never by "the grant succeeded". A signed-out render of this app is a
 * perfectly valid page: `/` draws the CUT DEMO BOOK to anyone without a session and the two books
 * look alike at a glance. Two probes, and neither writes anything:
 *   · `POST /api/reminders/send` with an empty body. The route reads the session FIRST and answers
 *     401 when there is none; with a session it falls through to the argument check and answers
 *     400 "invoiceId and body are required". So 400 is proof of a session and nothing is written
 *     on either branch.
 *   · the console itself, asserted on this tenant's own client name rather than on a 200.
 */
const cookieHeader = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
const probe = await fetch(`${APP}/api/reminders/send`, {
  method: "POST",
  headers: { cookie: cookieHeader, "content-type": "application/json" },
  body: "{}",
});
if (probe.status !== 400) {
  console.error(
    `cookies were set but ${APP}/api/reminders/send answered ${probe.status} ` +
      `(400 = signed in, 401 = the server still reads signed out, 403 = the demo account)`,
  );
  process.exit(1);
}

const page = await fetch(`${APP}/`, { headers: { cookie: cookieHeader } });
const html = await page.text();
if (!html.includes("Harrowgate Joinery") && !html.includes("Westbourne Fitout")) {
  console.error("the console rendered without this tenant's own names; it is drawing the demo book");
  process.exit(1);
}

fs.writeFileSync(
  OUT,
  JSON.stringify(
    { email: EMAIL, userId: data.session.user.id, capturedAt: new Date().toISOString(), appUrl: APP, cookies },
    null, 2,
  ),
);

console.log(`signed in as ${EMAIL} (${data.session.user.id})`);
console.log(`send probe ${probe.status}, console rendered the tenant book`);
for (const c of cookies) console.log(`  ${c.name} (${c.value.length} bytes)`);
console.log(`-> ${path.relative(process.cwd(), OUT)}`);
