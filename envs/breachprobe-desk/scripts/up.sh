#!/usr/bin/env bash
# Bring breachprobe-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, the three loopback scan targets, an app copy built against the LOCAL
# stack, and the product on 3851. Safe to re-run: every step either does nothing or does the
# same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This never starts one, never creates a
# second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds breachprobe's tables to it.
#
# ⛔ THE APP IS BUILT IN envs/breachprobe-desk/app, NEVER IN ~/CompoundLabs/breachprobe (rules 9
# and 12). Building a copy keeps the product tree clean, which is what the 00:30 deploy sweep
# requires, and `tools/stale-build.sh` is called on both sides of the build because an
# environment's own .next goes stale exactly the way a product's does.
#
# ⛔ WHAT IS DELIBERATELY NOT SET, AND WHY EACH ONE MATTERS ON THIS PRODUCT:
#   STRIPE_SECRET_KEY   absent. Every route that reads it calls api.stripe.com for real.
#                       POST /api/checkout answers 503 without it and reconcile() returns an
#                       empty sweep, both of which are the paths this environment grades.
#   RESEND_API_KEY      absent. Nothing may send real mail, so send() returns false and the
#                       report_emailed_at flag stays null, which is the product's own design.
#   every model key     absent. This product calls no model at all, so there is nothing to spend.
#
# ⛔ WHAT IS SET, AND IS NOT WHAT IT LOOKS LIKE:
#   STRIPE_WEBHOOK_SECRET is an HMAC key and nothing else. The webhook's refund and dispute
#   branch verifies a signature locally and then only reads and writes Postgres, so the dispute
#   task signs its own event with this value and no Stripe API is touched. It is a fabricated
#   string, not a Stripe secret.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${DESK_APP_DIR:-$HOME/CompoundLabs/breachprobe}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3851}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"

. "$HERE/../../tools/stale-build.sh"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_SRC" ] || { echo "product tree not found at $APP_SRC (set DESK_APP_DIR)" >&2; exit 1; }

say "supabase stack"
docker ps --format '{{.Names}}' | grep -qx "$DB" \
  || { echo "the shared stack is not running; start it from envs/unemploy-desk/stack" >&2; exit 1; }
echo "already running"

say "keys"
STATUS="$(cd "$STACK" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/breachprobe-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -f "/tmp/breachprobe-$f" 2>&1 \
    | grep -vE "NOTICE|already exists|setval|^-+$|^\s*$|^\(1 row\)$" || true
  echo "applied $f"
done

# ⛔ RULE 10. One NULL token column anywhere in the SHARED auth.users 500s admin list-users for
# every environment on this stack, and a product reads that 500 as "there is no demo account".
# BreachProbe has no accounts, never calls GoTrue and creates no auth.users row, so it cannot
# cause this and cannot be hurt by it. The repair still runs, because this environment shares the
# table with the ones that can, and leaving a neighbour broken is the same as breaking it.
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

say "scan targets"
# The three fabricated apps the scanner is allowed to point at, on 3852, 3853 and 3854. 3859 is
# left closed on purpose: it is the unreachable host the nightly task needs.
if curl -s -o /dev/null -m 2 "http://127.0.0.1:3852/"; then
  echo "already serving on 3852, 3853, 3854"
else
  nohup node "$HERE/target/serve.mjs" >/tmp/breachprobe-desk-targets.log 2>&1 &
  TPID=$!
  disown "$TPID" 2>/dev/null || true
  echo "$TPID" > /tmp/breachprobe-desk-targets.pid
  for _ in $(seq 1 20); do
    curl -s -o /dev/null -m 1 "http://127.0.0.1:3852/" && break
    sleep 0.5
  done
  echo "started (pid $TPID, log /tmp/breachprobe-desk-targets.log)"
fi
curl -s -o /dev/null -m 2 "http://127.0.0.1:3859/" \
  && { echo "something is listening on 3859; the nightly task needs it closed" >&2; exit 1; } \
  || echo "3859 closed, as the unreachable-host case requires"

say "app copy"
# ⛔ THE PRODUCT'S OWN .env.local IS EXCLUDED, AND THAT IS THE WHOLE POINT OF RULE 9. It carries
# the LIVE Stripe secret key, the production Supabase service role key and the Resend key. Copied
# in, even for the moment before the block below overwrites it, it is a live payment credential
# sitting in this tree, and this product's routes call api.stripe.com the instant one is present.
CHANGED="$(rsync -a --delete --itemize-changes \
      --exclude node_modules --exclude .next --exclude .open-next \
      --exclude .git --exclude .vercel --exclude .wrangler \
      --exclude '.env*' \
      "$APP_SRC"/ "$APP"/ | grep -vc '^$' || true)"
echo "copied to $APP ($CHANGED paths changed)"

say "app build"
cd "$APP"
cat > .env.local <<EOF
SUPABASE_URL=$API_URL
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
STRIPE_WEBHOOK_SECRET=whsec_breachprobe_desk_fixture
MONITOR_SECRET=breachprobe-desk-monitor-secret
SITE_URL=http://127.0.0.1:$PORT
EOF
[ -d node_modules ] || npm ci --no-audit --no-fund
# Rule 9's other half: a build that cannot be current is removed before anything decides whether
# to build, and the port is freed with it, because a server started from the old build keeps
# serving it no matter what gets built next.
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
# ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). The dev server's hydration is what makes
# a React handler silently not fire, and both browser tasks here are a click.
REBUILT=0
if [ ! -d .next ] || [ "$CHANGED" -gt 0 ]; then
  npm run build
  REBUILT=1
fi
desk_stamp_build "$APP" "$API_URL"
echo "built"

say "app"
# A REBUILD WITHOUT A RESTART SERVES THE OLD BUNDLE. `next start` reads .next once, at boot.
if [ "$REBUILT" = 1 ] && [ -f /tmp/breachprobe-desk-app.pid ]; then
  kill "$(cat /tmp/breachprobe-desk-app.pid)" 2>/dev/null || true
  sleep 2
fi
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED, and preloaded with the egress guard. See target/egress-guard.cjs: anything the
  # product tries to fetch that is not loopback is refused at the socket and printed in the log.
  # ⛔ BREACHPROBE_ALLOW_PRIVATE_TARGETS IS WHAT LETS THIS ENVIRONMENT EXIST, and it is the only
  # thing that sets it. The product refuses a private or loopback target now, because POST /api/scan
  # is unauthenticated and its findings quote a redacted excerpt of every credential it matched, so
  # an anonymous caller could name an internal host and read it back. This environment's targets are
  # the three fabricated sites it serves itself on loopback, so it has to be allowed past that
  # refusal, and it says so out loud rather than the product carrying a quiet exception. The egress
  # guard below is the other half: it still refuses anything that is NOT loopback.
  BREACHPROBE_ALLOW_PRIVATE_TARGETS=1 \
  NODE_OPTIONS="--require $HERE/target/egress-guard.cjs" \
    nohup npm start >/tmp/breachprobe-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/breachprobe-desk-app.pid
  for _ in $(seq 1 60); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/breachprobe-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app      http://127.0.0.1:$PORT"
echo "  targets  http://127.0.0.1:3852  http://127.0.0.1:3853  http://127.0.0.1:3854"
echo "  prove    uv run python envs/breachprobe-desk/adversarial/prove_graders.py"
