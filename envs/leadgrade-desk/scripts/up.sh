#!/usr/bin/env bash
# Bring leadgrade-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, four auth users, an app copy built against the LOCAL stack on 3753, and a
# captured session. Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ THE PRODUCT TREE IS READ, NEVER WRITTEN, AND NEVER BUILT IN PLACE (rules 9 and 12).
# The app is rsync'd into envs/leadgrade-desk/app (gitignored) and built THERE, with .env* excluded
# so the product's own file cannot come along. That file names the PRODUCTION Supabase project and
# carries this deployment's CRON_SECRET and the shared HubSpot client secret, and NEXT_PUBLIC_* is
# inlined at BUILD time: reusing the product's .next, or copying its env, would serve the
# production anon key to the browser and open real sessions against the live project.
#
# ⛔ NO KEY THAT COSTS ANYTHING IS SET, ON PURPOSE.
#   · no ANTHROPIC_API_KEY or OPENAI_API_KEY. LeadGrade calls no model at all, so there is nothing
#     to stub; the absence is stated so a later edit cannot quietly add one.
#   · no STRIPE_SECRET_KEY. /api/checkout and /api/billing/portal read it FIRST and answer 503
#     before any fetch is built, so nothing here can reach api.stripe.com with a fixture's
#     `cus_FIXTURE_*` id.
#   · STRIPE_WEBHOOK_SECRET is a fixture string. The webhook route verifies an HMAC over the raw
#     body with node's own crypto and makes no outbound call whatsoever, so the graders sign their
#     own events and the route runs for real.
#   · no HUBSPOT_CLIENT_ID / SECRET / REDIRECT_URI. The OAuth start answers 501 "not configured",
#     and every rail path resolves its token through `accessTokenFor()`, which answers null for
#     the fixture's token-less integration rows.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/leadgrade}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3753}"

HARLOW_ID="00000000-0000-4000-8000-0000000ff001"
HARLOW_EMAIL="ops@harlow-instruments.example"
CALLOWAY_ID="00000000-0000-4000-8000-0000000ff002"
CALLOWAY_EMAIL="desk@calloway-partners.example"
MERROW_ID="00000000-0000-4000-8000-0000000ff003"
MERROW_EMAIL="hello@merrow-tooling.example"
# Signed up and never paid, which is an ordinary state in a product with no free tier: no
# subscription row exists for this account at all.
THORNBURY_ID="00000000-0000-4000-8000-0000000ff004"
THORNBURY_EMAIL="hello@thornbury-glass.example"
PASSWORD="${DESK_PASSWORD:-leadgrade-fixture-password}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$SRC" ] || { echo "product tree not found at $SRC (set DESK_APP_SRC)" >&2; exit 1; }

say "supabase stack"
docker ps --format '{{.Names}}' | grep -qx "$DB" || {
  echo "the shared stack is not running. Start it from $STACK, never a second one." >&2
  exit 1
}
echo "already running ($DB)"

say "keys"
STATUS="$(cd "$STACK" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/leadgrade-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/leadgrade-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# Rule 10. One NULL token column anywhere in the SHARED auth.users makes GoTrue's admin
# list-users answer 500 for every caller on this stack, not just the broken row, and a product
# reads that 500 as "there is no such account". Repair first, then probe.
say "auth.users token repair (rule 10)"
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
probe=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE")
[ "$probe" = "200" ] || { echo "admin list-users still answers $probe" >&2; exit 1; }
echo "admin list-users 200"

say "fixture auth users"
# ⛔ ...0ff001 through ...0ff004 are this environment's namespace in the SHARED auth.users
# (rule 11). Nothing else on this stack may hold them; a colliding uuid fails on users_pkey and
# the second environment to run its up.sh is the one that discovers it.
mkuser() {
  local id="$1" email="$2" company="$3"
  local code
  code=$(curl -s -o /tmp/leadgrade-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
    -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$id\",\"email\":\"$email\",\"password\":\"$PASSWORD\",\"email_confirm\":true,\"user_metadata\":{\"company\":\"$company\"}}")
  case "$code" in
    200|201) echo "created $email" ;;
    422)     echo "already exists: $email" ;;
    *)       echo "unexpected $code for $email: $(cat /tmp/leadgrade-user.json)" >&2; exit 1 ;;
  esac
}
mkuser "$HARLOW_ID" "$HARLOW_EMAIL" "Harlow Instruments"
mkuser "$CALLOWAY_ID" "$CALLOWAY_EMAIL" "Calloway Partners"
mkuser "$MERROW_ID" "$MERROW_EMAIL" "Merrow Tooling"
mkuser "$THORNBURY_ID" "$THORNBURY_EMAIL" "Thornbury Glass"

# The seed writes leadgrade_settings and leadgrade_subscriptions rows that reference those uuids,
# so it is re-applied after the users exist. It is idempotent and scoped to its own rows.
docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/leadgrade-02-seed.sql" \
  2>&1 | grep -vE "NOTICE" || true
echo "fixture re-applied over the four accounts"

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' \
  --exclude '.env' --exclude '.env.*' \
  "$SRC"/ "$APP"/

# ⛔ THE SHIM, AND IT IS A DEFECT IN THE PRODUCT RATHER THAN A CONVENIENCE HERE.
# src/app/_lib/agent/schedule.ts imports ../../../../vercel.json and the product tree has no such
# file, so `npm run build` fails on a clean copy with "Module not found: Can't resolve
# '../../../../vercel.json'". Measured 2026-09-19; recorded in results.json at high severity and
# NOT fixed in the product repo. The two expressions in fixtures/vercel.json are read out of the
# product's own last successful build rather than invented; that file says where.
cp "$HERE/fixtures/vercel.json" "$APP/vercel.json"

cat > "$APP/.env.local" <<ENVFILE
# Written by envs/leadgrade-desk/scripts/up.sh. The product's own .env.local is excluded from the
# rsync: it names the PRODUCTION Supabase project and carries live deployment secrets.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$ANON
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
CRON_SECRET=leadgrade-desk-cron-fixture
# A fixture string, not a Stripe secret. The webhook route computes an HMAC with node's own
# crypto and makes no outbound call, so the graders sign their own events and the route runs.
STRIPE_WEBHOOK_SECRET=whsec_leadgrade_desk_fixture_not_a_stripe_secret
# Deliberately absent: STRIPE_SECRET_KEY, HUBSPOT_CLIENT_ID, HUBSPOT_CLIENT_SECRET,
# HUBSPOT_REDIRECT_URI, ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY.
ENVFILE
echo "copied to $APP"

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the server started
# from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
cd "$APP"
[ -d node_modules ] || npm ci --silent --no-audit --no-fund
# ⛔ THE PRODUCT'S OWN `npm run build`, never `npx next build` (rule 6).
[ -d .next ] || npm run build
echo "built"

desk_stamp_build "$APP" "$API_URL"

say "app"
if curl -s -o /dev/null -m 3 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  nohup npm start >/tmp/leadgrade-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/leadgrade-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/leadgrade-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
DESK_API_URL="$API_URL" DESK_ANON_KEY="$ANON" DESK_APP_URL="http://127.0.0.1:$PORT" \
DESK_EMAIL="$HARLOW_EMAIL" DESK_PASSWORD="$PASSWORD" node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT/"
echo "  prove   uv run python envs/leadgrade-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py leadgrade-desk"
