#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   bash envs/fetchdue-desk/scripts/up.sh
#
# Schema, RLS, the estate's auth-event function, the three fixture auth users, the fixture, a copy
# of the app built against the LOCAL stack, the app on 3757, and a captured session. Safe to
# re-run: every step either does nothing or does the same thing again.
#
# THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never calls `supabase start`,
# never creates a second stack and never changes its ports. It reads the running stack's keys and
# adds FetchDue's 25 tables to it.
#
# THE APP IS COPIED AND BUILT HERE, NEVER SERVED OUT OF THE PRODUCT TREE (rule 9). `NEXT_PUBLIC_*`
# is inlined into the browser bundle at BUILD time, so serving the product's own `.next` would
# hand the browser the PRODUCTION Supabase url and anon key and open real sessions against the live
# project. `envs/*/app/` is gitignored. The product tree is never written to and git is never run.
#
# EVERY THIRD PARTY KEY IS DELIBERATELY ABSENT, AND EACH ABSENCE IS A PRODUCT PATH THIS
# ENVIRONMENT GRADES RATHER THAN A GAP IT WORKS AROUND:
#
#   RESEND_API_KEY            the email capability resolves its GRACEFUL STUB, so `isOk(res)` is
#                             false and both send paths record the row `scheduled` / `failed`
#                             instead of `sent`. That is the product's own no-rail behaviour, and
#                             it is what makes "nothing was fabricated as sent" a check.
#   TELNYX_API_KEY            the SMS capability does the same.
#   ANTHROPIC_API_KEY         no model call anywhere, ever. HARD RULE #12: the paid keys are spent
#   OPENAI_API_KEY            by a paying customer's own request inside a shipped product and by
#   GEMINI_API_KEY            nothing else. FetchDue's own 2026-09-05 audit found this product
#                             spending two model calls per inbound reply with no plan check, so it
#                             is the last product in the estate that should be probed with a key
#                             present. With all three absent, `draftReminder` returns
#                             `{ok:false, reason}` and the cadence writes the deterministic
#                             template with the rail's refusal recorded on the row, which is a
#                             branch this environment grades.
#   STRIPE_SECRET_KEY         absent, not a placeholder. A Stripe client built on a placeholder
#                             succeeds and the first call still goes out. Absent makes an outbound
#                             call impossible: `lib/stripe.ts stripe()` throws before it is
#                             constructed, `createInvoicePaymentLink` and
#                             `createInstallmentPaymentLink` return null at their first line, and
#                             `revokeStripeConnect` refuses before its fetch.
#   STRIPE_WEBHOOK_SECRET     see README, "what could not be graded": the webhook reads BOTH Stripe
#                             variables before it verifies anything, so its HMAC path cannot be
#                             exercised without arming a key that makes api.stripe.com reachable.
#   STRIPE_PRICE_ID_*         `/api/billing/checkout` reads the price id BEFORE it touches Stripe
#                             and answers 500 "No price configured", so the route is closed twice.
#   QUICKBOOKS_CLIENT_ID      the OAuth start route answers 501 and builds no vendor URL; the
#   XERO_CLIENT_ID            callback breaks out of its switch before any code exchange; and
#   HUBSPOT_CLIENT_ID         `revokeProviderGrant` refuses rather than reaching Intuit or Xero.
#   MICROSOFT_FETCHDUE_*      no mailbox can be reached, so `sendAsMicrosoft365` returns not-ok and
#   STRIPE_CONNECT_CLIENT_ID  every email falls through to the absent Resend rail.
#   GCP_BQ_SA_KEY             the inference telemetry sink is a silent no-op without it.
#   FETCHDUE_TOKEN_ENCRYPTION_KEY  @compound/crypto passes plaintext through when unset, which is
#                             the legacy path; it is irrelevant here because every seeded token
#                             column is NULL.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/fetchdue}"
STACK_DIR="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3757}"
PASSWORD="${DESK_PASSWORD:-fetchdue-fixture-password}"
DESK_CRON="${DESK_CRON_SECRET:-fetchdue-desk-cron-secret}"

DESK_USER="00000000-0000-4000-8000-00000002c001:desk@harrowgate-joinery.example"
NEIGHBOUR="00000000-0000-4000-8000-00000002c002:books@pellingford-survey.example"
FREE_USER="00000000-0000-4000-8000-00000002c003:hello@oakmere-signage.example"

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

say "schema, rls, auth events"
for f in 01-schema.sql 04-auth-events.sql 03-rls.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/fetchdue-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f "/tmp/fetchdue-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# RULE 10. auth.users is shared by every environment on this stack, and ONE null token column
# anywhere in it makes GoTrue's admin list-users answer 500 for EVERY caller. Four of FetchDue's
# five cron routes page through `sb.auth.admin.listUsers` to find the shared demo account and skip
# it, and each of them reads the failure as `data?.users` being undefined, which silently resolves
# the demo id to null and takes the skip off. That is a wrong answer far away from its cause, so
# the repair runs before anything else and the probe below proves it took.
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
for pair in "$DESK_USER" "$NEIGHBOUR" "$FREE_USER"; do
  uid="${pair%%:*}"; mail="${pair##*:}"
  code=$(curl -s -o /tmp/fetchdue-desk-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
    -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$uid\",\"email\":\"$mail\",\"password\":\"$PASSWORD\",\"email_confirm\":true,\"user_metadata\":{\"signup_app\":\"fetchdue\"}}")
  case "$code" in
    200|201) echo "created $mail" ;;
    422) echo "already exists: $mail" ;;
    *) echo "unexpected $code for $mail: $(cat /tmp/fetchdue-desk-user.json)" >&2; exit 1 ;;
  esac
done

probe=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE")
[ "$probe" = "200" ] || { echo "admin list-users answered $probe, not 200 (rule 10)" >&2; exit 1; }
echo "admin list-users $probe"

# The fixture's foreign keys resolve only once the auth users exist, so the seed runs after them.
say "fixture"
docker cp "$HERE/sql/02-seed.sql" "$DB:/tmp/fetchdue-02-seed.sql" >/dev/null
docker exec "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f /tmp/fetchdue-02-seed.sql
echo "applied 02-seed.sql"

say "app copy"
mkdir -p "$HERE/app"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .git --exclude .open-next \
  --exclude .wrangler --exclude .vercel --exclude design-reviews --exclude promo \
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
       NEXT_PUBLIC_APP_URL="http://127.0.0.1:$PORT"
# Anything left in this shell from the caller's profile would defeat the point of the absences
# documented at the top of this file.
unset STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PRICE_ID_MONTHLY STRIPE_PRICE_ID_FIRM_MONTHLY \
      RESEND_API_KEY RESEND_FROM TELNYX_API_KEY TELNYX_CONNECTION_ID TELNYX_FROM_NUMBER \
      TELNYX_MESSAGING_PROFILE_ID TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN \
      ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY GCP_BQ_SA_KEY SERPAPI_KEY \
      QUICKBOOKS_CLIENT_ID QUICKBOOKS_CLIENT_SECRET QUICKBOOKS_REDIRECT_URI QUICKBOOKS_ENV \
      XERO_CLIENT_ID XERO_CLIENT_SECRET XERO_REDIRECT_URI \
      HUBSPOT_CLIENT_ID HUBSPOT_CLIENT_SECRET HUBSPOT_REDIRECT_URI \
      MICROSOFT_FETCHDUE_CLIENT_ID MICROSOFT_FETCHDUE_CLIENT_SECRET MICROSOFT_REDIRECT_URI \
      MICROSOFT_OAUTH_CLIENT_ID MICROSOFT_OAUTH_CLIENT_SECRET \
      STRIPE_CONNECT_CLIENT_ID STRIPE_CONNECT_REDIRECT_URI \
      FETCHDUE_TOKEN_ENCRYPTION_KEY REVALIDATE_SECRET || true
[ -d node_modules ] || npm ci --no-audit --no-fund
# PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6), and THE PRODUCT'S OWN `npm run build`, never
# `npx next build`: a product may put a prebuild in front of it that derives generated files, and
# `npx next build` skips every one of those. FetchDue's build is a bare `next build` today; running
# it through npm is still what rule 6 requires, because the day a prebuild is added nothing here
# has to change.
[ -d .next ] || npm run build
echo "built"

desk_stamp_build "$HERE/app" "$API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # Detached. Backgrounded with a plain ampersand the server belongs to this script's process
  # group, so whatever called up.sh takes the server down with it when it exits.
  nohup npm start >/tmp/fetchdue-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/fetchdue-desk-app.pid
  for _ in $(seq 1 60); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/fetchdue-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
DESK_API_URL="$API_URL" DESK_ANON_KEY="$ANON" DESK_APP_URL="http://127.0.0.1:$PORT" node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  prove   uv run python envs/fetchdue-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py fetchdue-desk"
