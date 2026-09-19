#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, the fixture, the three auth users, the app on 3756, and a captured session.
# Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND THIS SCRIPT NEVER STARTS ONE. Every product in the estate
# runs against one local stack, the same way they share one production project. It is brought up
# by envs/unemploy-desk/stack and this script only adds its own tables to it. `supabase start`,
# a second stack and a port change are all wrong here.
#
# ⛔ THE APP IS NOT IN THIS REPO. cardchase is a separate tree and the environment builds it from
# there, read only. Publishing this environment to someone without that tree needs the app
# vendored or its image published.
#
# ⛔ AND IT IS BUILT WITH NO STRIPE KEY, DELIBERATELY. `railFor()` in dispatch-run.ts falls back
# to `process.env.STRIPE_SECRET_KEY` when the integration row carries no key of its own, and that
# is the only path in the product from a cron tick to a real card. With the variable absent the
# rail is null, the dispatcher records `no_stripe_rail`, and nothing is ever charged. Checkout,
# the billing portal and the Stripe webhook all answer 503 or 500 for the same reason, which is
# the correct behaviour for all three and is why no task uses them.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${CARDCHASE_APP_DIR:-$HOME/CompoundLabs/cardchase}"
STACK_DIR="${CARDCHASE_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${CARDCHASE_DB_CONTAINER:-supabase_db_stack}"
PORT="${CARDCHASE_APP_PORT:-3756}"

OWNER_ID="00000000-0000-4000-9000-0000000000a1"
SPARE_ID="00000000-0000-4000-9000-0000000000a2"
DEMO_ID="00000000-0000-4000-9000-0000000000a3"
OWNER_EMAIL="${CARDCHASE_EMAIL:-ops@northlight-gear.example}"
SPARE_EMAIL="billing@harborline-supply.example"
DEMO_EMAIL="demo@thecompound.tech"
CRON_SECRET="${CARDCHASE_CRON_SECRET:-cardchase-desk-fixture-cron-secret}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_DIR" ] || { echo "app tree not found at $APP_DIR (set CARDCHASE_APP_DIR)" >&2; exit 1; }
docker ps --format '{{.Names}}' | grep -qx "$DB" \
  || { echo "the shared supabase stack is not running. Bring it up from $STACK_DIR." >&2; exit 1; }

# Read the keys off the running stack rather than hardcoding them: they are per-project and a
# stale copy here would fail as an auth error somewhere far away from its cause.
say "keys"
STATUS="$(cd "$STACK_DIR" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
if docker exec "$DB" psql -U postgres -d postgres -tAc \
     "select 1 from information_schema.tables where table_name='cardchase_failures'" | grep -q 1; then
  echo "skip 01-schema.sql (tables present)"
else
  docker cp "$HERE/sql/01-schema.sql" "$DB:/tmp/cc-01-schema.sql" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f /tmp/cc-01-schema.sql
  echo "applied 01-schema.sql"
fi

say "auth users"
for pair in "$OWNER_ID:$OWNER_EMAIL" "$SPARE_ID:$SPARE_EMAIL" "$DEMO_ID:$DEMO_EMAIL"; do
  uid="${pair%%:*}"; addr="${pair#*:}"
  code=$(curl -s -o /tmp/cc-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
    -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$uid\",\"email\":\"$addr\",\"email_confirm\":true}")
  case "$code" in
    200|201) echo "created $addr" ;;
    422)     echo "already exists: $addr" ;;
    *)       echo "unexpected $code for $addr: $(cat /tmp/cc-user.json)" >&2; exit 1 ;;
  esac
done

# ⛔ REPAIR THE SHARED auth.users TABLE, AND THIS IS NOT HOUSEKEEPING. GoTrue's admin list-users
# endpoint scans every row into a Go struct whose token fields are plain strings, so ONE row
# anywhere in the table with a NULL `confirmation_token`, `recovery_token`, `email_change` or
# `email_change_token_new` makes the whole endpoint answer
# `500 {"error_code":"unexpected_failure","msg":"Database error finding users"}` for everybody.
# GoTrue itself always writes '' and never NULL; a fixture that inserts users with raw SQL does
# not. Measured here on 2026-09-19: two users belonging to another environment's fixture carried
# NULLs, and with them present `listUsers()` returned an empty array to the app.
#
# That is not a cosmetic failure. `demoUserId()` in BOTH crons, and `resolveDemoUserId()` in the
# console's own tenant loader, resolve the shared demo account through that endpoint, and every
# one of them treats "not found" as null and carries on. The demo skip in the pass and in the
# dispatcher goes INERT: the demo book gets worked like any other account, the console renders
# "No Stripe account connected" signed out, and nothing errors anywhere. Two of this
# environment's graders assert the demo book was untouched, and they would have been asserting
# something the product was no longer doing.
#
# Rewriting NULL to '' is what GoTrue writes itself, so it changes nothing about those accounts.
# It runs on every bring-up rather than once, because the rows come back whenever a sibling
# environment re-applies its own fixture.
#
# ⛔ AND THE COUNT COMES BACK AS A COUNT, NOT THROUGH `grep -c`. Under `set -o pipefail` a
# `... | grep -c` on a repair that found nothing to do exits 1, which takes this whole script
# down on its SECOND run: the one where there is correctly nothing left to repair.
say "auth.users token repair"
REPAIRED=$(docker exec "$DB" psql -U postgres -d postgres -tAc "
  with fixed as (
  update auth.users set
    confirmation_token         = coalesce(confirmation_token, ''),
    recovery_token             = coalesce(recovery_token, ''),
    email_change               = coalesce(email_change, ''),
    email_change_token_new     = coalesce(email_change_token_new, ''),
    email_change_token_current = coalesce(email_change_token_current, ''),
    phone_change               = coalesce(phone_change, ''),
    phone_change_token         = coalesce(phone_change_token, ''),
    reauthentication_token     = coalesce(reauthentication_token, '')
  where confirmation_token is null or recovery_token is null or email_change is null
     or email_change_token_new is null or email_change_token_current is null
     or phone_change is null or phone_change_token is null or reauthentication_token is null
  returning 1)
  select count(*) from fixed")
echo "repaired ${REPAIRED} row(s)"

# Fail closed on the thing the repair exists to protect. A silent empty list here is how the
# demo skip stops working, and it is invisible from every other surface.
DEMO_SEEN=$(curl -s "$API_URL/auth/v1/admin/users?page=1&per_page=200" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(1 for u in d.get('users',[]) if u.get('email')=='$DEMO_EMAIL'))")
[ "$DEMO_SEEN" = "1" ] || {
  echo "the admin list-users endpoint cannot see $DEMO_EMAIL, so both crons will work the demo book" >&2
  exit 1
}
echo "admin list-users resolves the demo account"

# RLS and the fixture come AFTER the users, because every cardchase_* table has a foreign key
# onto auth.users and the seed would fail on a fresh project otherwise.
for f in 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/cc-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/cc-$f"
  echo "applied $f"
done

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the
# server started from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$APP_DIR" "$API_URL" "$PORT"
cd "$APP_DIR"
# ⛔ REBUILT AGAINST THE LOCAL STACK, ALWAYS. NEXT_PUBLIC_* are inlined into the client bundle at
# build time, so a .next left over from a production build ships the PRODUCTION Supabase url and
# anon key to the browser, and the sign in dialog would open a session against the live project.
# Next's own env loader never overwrites a variable already set in the process, so these win over
# the repo's .env.local.
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" CRON_SECRET="$CRON_SECRET" \
       NEXT_PUBLIC_APP_URL="http://127.0.0.1:$PORT" NEXT_PUBLIC_WEB_URL="http://127.0.0.1:$PORT"
unset STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET CARDCHASE_STRIPE_APP_SECRET
STAMP="$APP_DIR/.next/.cardchase-desk-built-for-$PORT"
if [ -f "$STAMP" ]; then
  echo "already built against the local stack"
else
  # ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER. The reference environment lost an afternoon to a
  # dev server whose hydration was broken, so React handlers never fired and the sign in form did
  # nothing at all while every page rendered perfectly.
  npm run build
  touch "$STAMP"
  echo "built"
fi

desk_stamp_build "$APP_DIR" "$API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED, AND THAT IS NOT DECORATION. Backgrounded with a plain `&` the server belongs to
  # this script's process group, so whatever called up.sh takes the server down with it when it
  # exits.
  # ⛔ BOUND TO 127.0.0.1, AND THAT DECIDES WHETHER SIGN IN WORKS. `auth/callback` redirects
  # to `new URL(req.url).origin`, which Next resolves to `localhost` on a default bind. The session
  # cookie was just written on host 127.0.0.1, browsers scope cookies by host, and localhost is a
  # different host: the page that comes back is signed out with a valid session sitting next to it.
  nohup npm start -- --port "$PORT" --hostname 127.0.0.1 >/tmp/cardchase-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/cardchase-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/cardchase-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  mailpit $(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["MAILPIT_URL"])')"
echo "  cron    Authorization: Bearer $CRON_SECRET"
echo "  prove   uv run python envs/cardchase-desk/adversarial/prove_graders.py"
echo "  rollout node envs/cardchase-desk/harness/rollout.mjs approve"
