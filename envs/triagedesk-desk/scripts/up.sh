#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   bash envs/triagedesk-desk/scripts/up.sh
#
# Schema, RLS, the four fixture auth users, the fixture, a copy of the app built against the LOCAL
# stack, the app on 3751, and a captured session. Safe to re-run: every step either does nothing
# or does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never calls `supabase start`,
# never creates a second stack and never changes its ports. It reads the running stack's keys and
# adds triagedesk's ten tables to it.
#
# ⛔ THE APP IS COPIED AND BUILT HERE, NEVER SERVED OUT OF THE PRODUCT TREE (rule 9).
# `NEXT_PUBLIC_*` is inlined into the browser bundle at BUILD time, so serving the product's own
# `.next` would hand the browser the PRODUCTION Supabase url and anon key and open real sessions
# against the live project. `envs/*/app/` is gitignored. The product tree is never written to and
# git is never run.
#
# ⛔ AND IT IS THE PRODUCT'S OWN `npm run build`, NEVER `npx next build` (rule 6). TriageDesk's
# build is `npm run icons && npm run book && next build`: two prebuild steps that regenerate
# `src/icons/*.generated.ts` and `src/data/demo-book.generated.ts`. `npx next build` skips both.
#
# ── THE KEYS THAT ARE SET, AND WHY EACH ONE HAS TO BE ────────────────────────────────────────
#
#   CRON_SECRET                       both cron routes compare `Authorization: Bearer <this>` and
#                                     answer 401 otherwise, so the dispatcher and the overnight
#                                     pass are only reachable with it.
#   STRIPE_WEBHOOK_SECRET             `/api/webhooks/stripe` REFUSES TO ACK without it (500, so
#                                     Stripe retries rather than dropping a payment). It is a
#                                     fixture string and the graders sign their own events with
#                                     it. ⛔ THIS ROUTE MAKES NO OUTBOUND CALL AT ALL: it HMACs
#                                     the raw body with node's own crypto and then writes rows,
#                                     so it runs here exactly as it does in production.
#   SLACK_TRIAGEDESK_SIGNING_SECRET   every Slack route calls `slackCredentials()` first and
#   SLACK_TRIAGEDESK_CLIENT_ID        returns null unless ALL THREE are present, and a null
#   SLACK_TRIAGEDESK_CLIENT_SECRET    signing secret makes `verifySlackSignature` answer 401. So
#                                     all three are set to fixture strings. The client pair has
#                                     exactly ONE consumer, `/api/slack/oauth/callback`, which
#                                     this suite never calls and which cannot be reached without
#                                     a real redirect back from slack.com carrying a code.
#
# ── THE KEYS THAT ARE DELIBERATELY ABSENT, AND WHAT EACH ABSENCE IS ─────────────────────────
#
#   STRIPE_SECRET_KEY        `/api/checkout` reads it FIRST and answers 503; the payments driver's
#                            `isConfigured()` is false so `/api/billing/portal` runs off the stub;
#                            `/welcome` returns before its fetch. Absent, never a placeholder: a
#                            client built on a placeholder succeeds and the first call still goes
#                            out. Absent is what makes an outbound call impossible.
#   ANTHROPIC_API_KEY        ⛔ RULE: A PAID LLM KEY IS SPENT BY A PAYING CUSTOMER AND BY NOTHING
#   OPENAI_API_KEY           ELSE. Not a test, not a warmup, not one call to see whether a key
#   GEMINI_API_KEY           works. With all three absent the inference capability resolves to
#                            `StubInferenceDriver`, which returns a typed "rail not connected"
#                            result, and the pass treats that as "could not classify" and hands
#                            the thread to a human. In this fixture the pass cannot even reach
#                            that point, because no mailbox grant carries a token.
#   GOOGLE_OAUTH_CLIENT_ID   the mailbox OAuth start route answers a redirect to
#   MICROSOFT_*_CLIENT_ID    `?rail=unavailable` and builds no vendor URL.
#   RESEND_API_KEY           nothing in this suite sends mail; the email capability stubs.
#   DEMO_SUPABASE_PASSWORD   `/demo` answers 500 before it touches anything, so the public demo
#                            route cannot reseed the shared demo account out from under a run.
#   FETCHDUE_TOKEN_ENCRYPTION_KEY  `decryptToken` answers null for a null column either way. The
#                            fixture's token columns are null, which is the whole guard.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/triagedesk}"
STACK_DIR="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3751}"
PASSWORD="${DESK_PASSWORD:-triagedesk-fixture-password}"
DESK_CRON="${DESK_CRON_SECRET:-triagedesk-desk-cron-secret}"
STRIPE_HOOK="${DESK_STRIPE_WEBHOOK_SECRET:-whsec_triagedesk_desk_fixture}"
SLACK_SIGNING="${DESK_SLACK_SIGNING_SECRET:-triagedesk-desk-slack-signing-secret}"

# ⛔ RULE 11. auth.users IS GENUINELY SHARED BY EVERY ENVIRONMENT ON THIS STACK. These four uuids
# are triagedesk-desk's block and nothing else on the stack may hold them, or the second up.sh to
# run fails on users_pkey. They are also in the README.
USER_A="00000000-0000-4000-8000-00000002b001"; EMAIL_A="desk@harrowgate-tools.example"
USER_B="00000000-0000-4000-8000-00000002b002"; EMAIL_B="ops@brightmere-audio.example"
USER_C="00000000-0000-4000-8000-00000002b003"; EMAIL_C="hello@lyndhurst-optics.example"
USER_D="00000000-0000-4000-8000-00000002b004"; EMAIL_D="book@harrowgate-tools.example"

say() { printf '\n== %s\n' "${1}"; }

[ -d "$APP_DIR" ] || { echo "app tree not found at $APP_DIR (set DESK_APP_DIR)" >&2; exit 1; }
docker ps --format '{{.Names}}' | grep -qx "$DB" || {
  echo "the shared supabase stack is not running ($DB). Start it from envs/unemploy-desk/stack." >&2
  exit 1
}

say "keys"
STATUS="$(cd "$STACK_DIR" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema and rls"
for f in 01-schema.sql 03-rls.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/triagedesk-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f "/tmp/triagedesk-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# ⛔ RULE 10. auth.users is shared, and ONE null token column anywhere in it makes GoTrue's admin
# list-users answer 500 for EVERY caller, not just the broken row. This product pages through
# listUsers in `/demo` and reads a user by id in the pipeline's plan gate, so a 500 there is a
# silent wrong answer a long way from its cause. Repair first, then probe.
say "auth.users token repair"
docker exec "$DB" psql -U postgres -d postgres -q -c "
update auth.users set
  confirmation_token = coalesce(confirmation_token, ''),
  recovery_token = coalesce(recovery_token, ''),
  email_change = coalesce(email_change, ''),
  email_change_token_new = coalesce(email_change_token_new, ''),
  email_change_token_current = coalesce(email_change_token_current, ''),
  phone_change = coalesce(phone_change, ''),
  phone_change_token = coalesce(phone_change_token, ''),
  reauthentication_token = coalesce(reauthentication_token, '')
where confirmation_token is null or recovery_token is null or email_change is null
   or email_change_token_new is null or email_change_token_current is null
   or phone_change is null or phone_change_token is null or reauthentication_token is null;"

say "fixture auth users"
make_user() {
  local id="$1" email="$2" company="$3"
  local code
  code=$(curl -s -o /tmp/triagedesk-desk-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
    -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$id\",\"email\":\"$email\",\"password\":\"$PASSWORD\",\"email_confirm\":true,\"user_metadata\":{\"signup_app\":\"triagedesk\",\"company\":\"$company\"}}")
  case "$code" in
    200|201) echo "created $email" ;;
    422) echo "already exists $email" ;;
    *) echo "unexpected $code for $email: $(cat /tmp/triagedesk-desk-user.json)" >&2; exit 1 ;;
  esac
}
make_user "$USER_A" "$EMAIL_A" "Harrowgate Tools"
make_user "$USER_B" "$EMAIL_B" "Brightmere Audio"
make_user "$USER_C" "$EMAIL_C" "Lyndhurst Optics"
make_user "$USER_D" "$EMAIL_D" "Harrowgate Tools"

probe=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE")
[ "$probe" = "200" ] || { echo "admin list-users answered $probe, not 200 (rule 10)" >&2; exit 1; }
echo "admin list-users $probe"

# The fixture's foreign keys resolve only once the auth users exist, so the seed runs after them.
say "fixture"
docker cp "$HERE/sql/02-seed.sql" "$DB:/tmp/triagedesk-02-seed.sql" >/dev/null
docker exec "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f /tmp/triagedesk-02-seed.sql
echo "applied 02-seed.sql"

say "app copy"
mkdir -p "$HERE/app"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .git --exclude .open-next \
  --exclude .wrangler --exclude .vercel --exclude design-reviews \
  --exclude '.env*' --exclude tsconfig.tsbuildinfo \
  "$APP_DIR"/ "$HERE/app"/
echo "copied to $HERE/app"

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the server started
# from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$HERE/app" "$API_URL" "$PORT"
cd "$HERE/app"
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" CRON_SECRET="$DESK_CRON" \
       STRIPE_WEBHOOK_SECRET="$STRIPE_HOOK" \
       SLACK_TRIAGEDESK_SIGNING_SECRET="$SLACK_SIGNING" \
       SLACK_TRIAGEDESK_CLIENT_ID="triagedesk-desk-fixture-client" \
       SLACK_TRIAGEDESK_CLIENT_SECRET="triagedesk-desk-fixture-client-secret"
# Anything left in this shell from the caller's profile would defeat the point of the absences
# documented at the top of this file.
unset STRIPE_SECRET_KEY \
      ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY \
      GOOGLE_OAUTH_CLIENT_ID GOOGLE_OAUTH_CLIENT_SECRET \
      MICROSOFT_TRIAGEDESK_CLIENT_ID MICROSOFT_TRIAGEDESK_CLIENT_SECRET \
      MICROSOFT_OAUTH_CLIENT_ID MICROSOFT_OAUTH_CLIENT_SECRET \
      RESEND_API_KEY DEMO_SUPABASE_PASSWORD FETCHDUE_TOKEN_ENCRYPTION_KEY || true
[ -d node_modules ] || npm ci --no-audit --no-fund
# ⛔ PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6), and the PRODUCT'S OWN `npm run build`.
[ -d .next ] || npm run build
echo "built"

desk_stamp_build "$HERE/app" "$API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # ⛔ A SUBSHELL AND `</dev/null`, NOT JUST `nohup ... &`. `nohup` blocks SIGHUP and `disown`
  # takes the job off this shell's table, and NEITHER of those survives the caller's process
  # GROUP being reaped, which is what a harness does when its shell exits. Measured 2026-09-19:
  # up.sh printed `started on 3751 (pid 97842)`, three later steps talked to the server happily,
  # and by the next command it was gone. The suite then read 93/93 with 10 skipped, which is the
  # app-down shape, and that is a bring-up reporting success and leaving nothing running.
  # Backgrounding INSIDE a subshell lets the subshell exit immediately, so the server is
  # reparented out of this group and outlives whatever called this script. `</dev/null` stops it
  # dying on a read from a terminal that has gone away.
  ( nohup npm start </dev/null >/tmp/triagedesk-desk-app.log 2>&1 & echo "$!" > /tmp/triagedesk-desk-app.pid )
  APP_PID="$(cat /tmp/triagedesk-desk-app.pid)"
  for _ in $(seq 1 60); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/triagedesk-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
DESK_API_URL="$API_URL" DESK_ANON_KEY="$ANON" DESK_APP_URL="http://127.0.0.1:$PORT" \
  DESK_EMAIL="$EMAIL_A" DESK_PASSWORD="$PASSWORD" node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  prove   uv run python envs/triagedesk-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py triagedesk-desk"
