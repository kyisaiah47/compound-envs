#!/usr/bin/env bash
# Bring outrip-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, an app copy built against the LOCAL stack, and the app on 3328.
# Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never starts one, never
# creates a second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds outrip's tables to it.
#
# ⛔ THE APP IS BUILT IN envs/outrip-desk/app, NEVER IN ~/CompoundLabs/outrip (rules 9 and 12).
# NEXT_PUBLIC_* is inlined at BUILD time, so reusing the product's own .next would serve the
# PRODUCTION Supabase url and publishable key to the browser and this environment would quietly
# be driving the live project. Building a copy also keeps the product tree clean, which is what
# the 00:30 deploy sweep requires.
#
# ⛔ NO PAID KEY IS EVER SET. outrip calls no model at all, so there is nothing to spend.
# STRIPE_SECRET_KEY below is NOT a Stripe key: the product uses it as the HMAC secret for the
# buyer cookie, the pending-order cookie, the recovery token and the click hash, and every route
# this environment grades reaches none of Stripe's API. STRIPE_WEBHOOK_SECRET is likewise only
# an HMAC key, which is what lets the reversal task sign its own event locally.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${DESK_APP_DIR:-$HOME/CompoundLabs/outrip}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3328}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_SRC" ] || { echo "product tree not found at $APP_SRC (set DESK_APP_DIR)" >&2; exit 1; }

say "supabase stack"
docker ps --format '{{.Names}}' | grep -qx "$DB" \
  || { echo "the shared stack is not running; start it from envs/unemploy-desk/stack" >&2; exit 1; }
echo "already running"

say "keys"
STATUS="$(cd "$STACK" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
PUBLISHABLE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["PUBLISHABLE_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/outrip-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -f "/tmp/outrip-$f" 2>&1 \
    | grep -vE "NOTICE|already exists|setval|^-+$|^\s*$|^\(1 row\)$" || true
  echo "applied $f"
done

# ⛔ RULE 10. One NULL token column anywhere in the SHARED auth.users 500s admin list-users for
# every environment on this stack, and a product reads that 500 as "there is no demo account".
# outrip has no accounts at all and never calls GoTrue, so it cannot cause this and cannot be
# hurt by it. The repair still runs, because this environment shares the table with the ones
# that do, and leaving a neighbour broken is the same as breaking it.
say "shared auth.users repair (rule 10)"
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
code=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/auth/v1/admin/users" \
       -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE")
echo "admin list-users -> $code (200 expected)"

say "app copy"
# ⛔ THE PRODUCT'S OWN .env.local IS EXCLUDED, AND THAT IS THE WHOLE POINT OF RULE 9. It carries
# the PRODUCTION Supabase url and publishable key; copied in, even for the moment before the
# block below overwrites it, it is a production credential sitting in this tree and one skipped
# step away from being built into a browser bundle. Same for .vercel, which holds
# .env.production.local.
#
# The rebuild is decided by what rsync actually moved rather than by whether .next happens to
# exist. `[ -d .next ] || build` looks idempotent and silently serves a stale bundle the first
# time the product changes underneath it.
CHANGED="$(rsync -a --delete --itemize-changes \
      --exclude node_modules --exclude .next --exclude .open-next \
      --exclude .git --exclude .vercel --exclude .wrangler \
      --exclude '.env*' \
      "$APP_SRC"/ "$APP"/ | grep -vc '^$' || true)"
echo "copied to $APP ($CHANGED paths changed)"

say "app build"
cd "$APP"
cat > .env.local <<EOF
NEXT_PUBLIC_SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$PUBLISHABLE
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
NEXT_PUBLIC_SITE_URL=http://127.0.0.1:$PORT
STRIPE_SECRET_KEY=outrip-desk-fixture-hmac-secret-not-a-stripe-key
STRIPE_WEBHOOK_SECRET=whsec_outrip_desk_fixture
EOF
[ -d node_modules ] || npm ci --no-audit --no-fund
# ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). The dev server's hydration is the thing
# that makes a React handler silently not fire, and both browser tasks here are a click.
REBUILT=0
if [ ! -d .next ] || [ "$CHANGED" -gt 0 ]; then
  npm run build
  REBUILT=1
fi
echo "built"

say "app"
# A REBUILD WITHOUT A RESTART SERVES THE OLD BUNDLE. `next start` reads .next once, at boot,
# so a server left running across a rebuild keeps answering from the build it started with
# and the whole copy step silently did nothing.
if [ "$REBUILT" = 1 ] && [ -f /tmp/outrip-desk-app.pid ]; then
  kill "$(cat /tmp/outrip-desk-app.pid)" 2>/dev/null || true
  sleep 2
fi
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/packs"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED. Backgrounded with a plain `&` the server belongs to this script's process
  # group, so whatever called up.sh takes the server down with it when it exits.
  nohup npm start >/tmp/outrip-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/outrip-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/packs" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/outrip-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app    http://127.0.0.1:$PORT"
echo "  board  http://127.0.0.1:$PORT/"
echo "  prove  uv run python envs/outrip-desk/adversarial/prove_graders.py"
