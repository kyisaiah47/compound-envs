#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Product bundles, schema, RLS, a fresh fixture, the fixture's auth user, the app on 3754, and a
# captured session. Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ IT DOES NOT START A SUPABASE STACK. The estate shares ONE local stack and every product's
# fixture lives in it beside the others. If it is not already up, bring it up from the stack
# directory this repo already owns (envs/unemploy-desk/stack) rather than creating a second one
# here: a second stack means a second set of ports and a second copy of every other product's
# tables.
#
# ⛔ AND THE APP IS NOT IN THIS REPO. clausewatch is a separate tree and this builds it from
# there. It never writes to that tree's tracked files: `next build` is invoked directly rather
# than through `npm run build`, because the package script runs `npm run icons` first and that
# generator writes src/icons/phosphor.generated.ts and src/logos/logos.generated.ts. Those files
# are committed, they are already current, and touching them on every bring-up would put a
# product repository into a dirty state at 00:30, which costs it its nightly deploy.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/clausewatch}"
STACK_DIR="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3754}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_DIR" ] || { echo "clausewatch tree not found at $APP_DIR (set DESK_APP_DIR)" >&2; exit 1; }

say "supabase stack"
if ! docker ps --format '{{.Names}}' | grep -qx "$DB"; then
  echo "the shared stack is not running." >&2
  echo "start it once, from the directory that owns it:" >&2
  echo "  (cd $STACK_DIR && supabase start)" >&2
  exit 1
fi
echo "already running ($DB)"

# Read the keys off the running stack rather than hardcoding them: they are per-project and a
# stale copy here would fail as an auth error somewhere far away from its cause.
say "keys"
STATUS="$(cd "$STACK_DIR" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
MAILPIT="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["MAILPIT_URL"])')"
echo "api $API_URL"

say "product bundles"
"$HERE/scripts/build-product.sh"

say "fixture"
# ⛔ THE FIXTURE IS BUILT FRESH ON EVERY BRING-UP, and that is not churn. Its dates are relative
# to the day it is written, exactly as the product's own seed-demo.ts computes its dates, because
# a notice deadline that lapsed last month leaves a queue with nothing due in it and an empty
# queue cannot carry a task. The generator reads the fixture with the product's own extractor and
# refuses to write a seed whose premises no longer hold.
(cd "$HERE" && node scripts/make-seed.mjs)

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/cw-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/cw-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

say "fixture auth user"
USER_ID="$(python3 -c 'import json;print(json.load(open("'"$HERE"'/fixtures/facts.json"))["desk_user"])')"
EMAIL="${DESK_EMAIL:-$(python3 -c 'import json;print(json.load(open("'"$HERE"'/fixtures/facts.json"))["desk_email"])')}"
code=$(curl -s -o /tmp/cw-desk-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
  -d "{\"id\":\"$USER_ID\",\"email\":\"$EMAIL\",\"email_confirm\":true}")
case "$code" in
  200|201) echo "created $EMAIL" ;;
  422) echo "already exists" ;;
  *)
    # ⛔ auth.users IS THE ONE TABLE EVERY PRODUCT'S ENVIRONMENT SHARES on this stack, so a
    # duplicate here is either this fixture's own user from a previous bring-up (fine) or another
    # environment holding the same uuid under a different address (not fine, and the raw error
    # says nothing about which). Ask the database which one it is.
    held="$(docker exec "$DB" psql -U postgres -d postgres -tAc \
      "select email from auth.users where id = '$USER_ID'")"
    if [ "$held" = "$EMAIL" ]; then
      echo "already exists"
    else
      echo "uuid $USER_ID is already held by '${held:-another schema}', not $EMAIL." >&2
      echo "another environment on this shared stack owns it; change DESK_USER in" >&2
      echo "scripts/make-seed.mjs. Raw: $(cat /tmp/cw-desk-user.json)" >&2
      exit 1
    fi
    ;;
esac
# The uuid has to match the cw_members row the seed writes, or requireMember() throws Forbidden
# for an account that looks perfectly signed in.
docker exec "$DB" psql -U postgres -d postgres -tAc \
  "select case when exists (select 1 from cw_members m join auth.users u on u.id = m.user_id
     where m.email = '$EMAIL') then 'membership ok' else 'MEMBERSHIP MISSING' end"

say "app build"
cd "$APP_DIR"
# ⛔ EVERY NEXT_PUBLIC_* VALUE IS INLINED AT BUILD TIME, so a build made against production points
# the browser client at the production Supabase project no matter what the server environment
# says. A stamp records which API the current build was made for, and a mismatch forces a build.
# Without this the sign-in in harness/signin.mjs asks PRODUCTION for a magic link.
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" \
       NEXT_PUBLIC_SITE_URL="http://127.0.0.1:$PORT"
# ⛔ FIVE ENVIRONMENT VARIABLES ARE LEFT UNSET ON PURPOSE, and each absence is load-bearing:
#   RESEND_API_KEY, RESEND_FROM   `deliver()` returns "No mail transport configured." before it
#                                 opens a socket, so the sweep task can run for real and NOTHING
#                                 leaves the machine.
#   CRON_SECRET                   the dispatch and nightly routes guard with `if (secret && ...)`,
#                                 so an unset secret leaves them reachable, which is what makes
#                                 the sweep a task an agent can perform.
#   STRIPE_SECRET_KEY,            checkout, the billing portal and the webhook are out of scope.
#   STRIPE_WEBHOOK_SECRET         See the README.
unset RESEND_API_KEY RESEND_FROM CRON_SECRET STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET || true
STAMP="$APP_DIR/.next/.clausewatch-desk-built-for"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$API_URL" ]; then
  echo "building against $API_URL (the existing build, if any, was for another API)"
  ./node_modules/.bin/next build
  echo "$API_URL" > "$STAMP"
else
  echo "already built against $API_URL"
fi

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED, AND THAT IS NOT DECORATION. Backgrounded with a plain `&` the server belongs to
  # this script's process group, so whatever called up.sh takes the server down with it when it
  # exits: the app serves, the wrapper ends, and the port goes dead with nothing in any log to
  # say why. nohup plus disown detaches it from both.
  nohup ./node_modules/.bin/next start -p "$PORT" >/tmp/clausewatch-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/clausewatch-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/clausewatch-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
node signin.mjs

say "ready"
echo "  app      http://127.0.0.1:$PORT"
echo "  mailpit  $MAILPIT"
echo "  prove    uv run python envs/clausewatch-desk/adversarial/prove_graders.py"
echo "  upload   node envs/clausewatch-desk/harness/rollout.mjs"
echo "  api      node envs/clausewatch-desk/harness/act.mjs dismiss|approve-yard|kill-notice|sweep"
