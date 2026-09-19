#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, the auth trigger, RLS, the fixture, a BUILT COPY of the product on 3309.
# Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ IT DOES NOT START A SUPABASE STACK. The estate shares ONE local stack and every product's
# fixture lives in it beside the others. If it is not already up, bring it up from the directory
# this repo already owns (envs/unemploy-desk/stack) rather than creating a second one here: a
# second stack means a second set of ports and a second copy of every other product's tables.
#
# ⛔ THE PRODUCT IS COPIED OUT OF ITS OWN TREE AND BUILT HERE, AND THAT IS NOT TIDINESS.
# Every NEXT_PUBLIC_* value is inlined into the browser bundle at BUILD time. A build made in the
# product's own tree against production serves the PRODUCTION Supabase url and anon key to the
# browser, so the sign-up form on /sign-up would open a real account against the live project.
# Copying to envs/frontwire-desk/app (gitignored) and building there also keeps the product tree
# clean, which matters on its own: a product tree that is dirty at 00:30 is refused by the
# nightly deploy sweep and that product ships nothing that night.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${DESK_APP_SRC:-$HOME/CompoundLabs/frontwire}"
APP_DIR="$HERE/app"
STACK_DIR="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3309}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$SRC_DIR" ] || { echo "frontwire tree not found at $SRC_DIR (set DESK_APP_SRC)" >&2; exit 1; }

say "supabase stack"
if ! docker ps --format '{{.Names}}' | grep -qx "$DB"; then
  echo "the shared stack is not running." >&2
  echo "start it once, from the directory that owns it:" >&2
  echo "  (cd $STACK_DIR && supabase start)" >&2
  exit 1
fi
echo "already running ($DB)"

say "keys"
STATUS="$(cd "$STACK_DIR" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
MAILPIT="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["MAILPIT_URL"])')"
echo "api $API_URL"

# ⛔ RULE 10. One NULL token column anywhere in the shared auth.users makes GoTrue's admin
# list-users answer 500 for EVERY caller on this stack, not just the row that is broken, and a
# product reads that 500 as "there is no account" rather than as an error. Repair, then probe.
say "shared auth.users repair"
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
[ "$code" = "200" ] || { echo "admin list-users answered $code, not 200" >&2; exit 1; }
echo "admin list-users 200"

say "schema, trigger, rls, fixture"
for f in 01-schema.sql 04-auth-trigger.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/fw-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/fw-$f" \
    2>&1 | grep -vE "NOTICE" || true
  echo "applied $f"
done

say "app copy"
rsync -a --delete --exclude node_modules --exclude .next --exclude .open-next \
      --exclude .git --exclude .vercel --exclude .wrangler --exclude .env.local \
      "$SRC_DIR"/ "$APP_DIR"/
echo "copied $SRC_DIR -> $APP_DIR"

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the
# server started from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$APP_DIR" "$API_URL" "$PORT"
cd "$APP_DIR"
# ⛔ SPEND. RESEND_API_KEY is left unset on purpose: sendEmail() logs and returns null before it
# opens a socket, so nothing this environment does can send real mail. STRIPE_SECRET_KEY is a
# placeholder that cannot authenticate against anything; the only Stripe code this environment
# reaches is `stripe.webhooks.constructEvent`, which is an HMAC over the request body and makes
# no network call at all. STRIPE_WEBHOOK_SECRET is a value this environment chose and signs with
# itself. CRON_SECRET stays unset, which leaves /api/digest-items answering 401 by its own first
# branch, which is what this environment wants: its honest path renders through the production
# email-render edge function.
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" \
       NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" \
       STRIPE_SECRET_KEY="${DESK_STRIPE_KEY:-sk_test_frontwire_desk_placeholder_not_a_real_key}" \
       STRIPE_WEBHOOK_SECRET="${DESK_STRIPE_WEBHOOK_SECRET:-whsec_frontwire_desk_local_only}" \
       STRIPE_PRICE_MONTHLY="price_frontwire_desk_monthly" \
       STRIPE_PRICE_YEARLY="price_frontwire_desk_yearly"
unset RESEND_API_KEY CRON_SECRET NEXT_PUBLIC_SITE_URL || true
[ -d node_modules ] || npm ci --silent --no-audit --no-fund
STAMP="$APP_DIR/.next/.frontwire-desk-built-for"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$API_URL" ]; then
  echo "building against $API_URL (the existing build, if any, was for another API)"
  ./node_modules/.bin/next build
  echo "$API_URL" > "$STAMP"
else
  echo "already built against $API_URL"
fi

desk_stamp_build "$APP_DIR" "$API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/contact"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED, AND THAT IS NOT DECORATION. Backgrounded with a plain `&` the server belongs to
  # this script's process group, so whatever called up.sh takes the server down with it when it
  # exits: the app serves, the wrapper ends, and the port goes dead with nothing in any log to
  # say why. nohup plus disown detaches it from both.
  nohup ./node_modules/.bin/next start -p "$PORT" >/tmp/frontwire-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/frontwire-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/contact" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/frontwire-desk-app.log)"
fi

say "ready"
echo "  app      http://127.0.0.1:$PORT"
echo "  mailpit  $MAILPIT"
echo "  prove    uv run python envs/frontwire-desk/adversarial/prove_graders.py"
echo "  rollout  node envs/frontwire-desk/harness/rollout.mjs"
