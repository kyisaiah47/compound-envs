#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, fixture, RLS and the low-star trigger, the fixture's auth user, a copy of the app built
# against the LOCAL stack, the app on 3752, and a captured session. Safe to re-run: every step
# either does nothing or does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never calls `supabase start`,
# never creates a second stack and never changes its ports. It reads the running stack's keys and
# adds starreply's tables to it.
#
# ⛔ THE APP IS COPIED AND BUILT HERE, NEVER SERVED OUT OF THE PRODUCT TREE. `NEXT_PUBLIC_*` is
# inlined into the browser bundle at BUILD time, so serving the product's own `.next` would hand
# the browser the PRODUCTION Supabase url and anon key and open real sessions against the live
# project. `envs/*/app/` is gitignored. The product tree is never written to.
#
# ⛔ NO MODEL KEY IS EXPORTED, ON PURPOSE. `@compound/integrations` resolves to
# `src/console/vendor/integrations.ts`, which is the inference rail with no key in it:
# `inference.text()` answers a stub, `classifyReview` falls through to `classifyLocally`, and the
# product's own documented degraded path is what runs. No paid API is reachable from here.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/starreply}"
STACK_DIR="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3752}"
EMAIL="${DESK_EMAIL:-desk@bloomwelldental.example}"
PASSWORD="${DESK_PASSWORD:-desk-fixture-password}"
USER_ID="00000000-0000-4000-8000-0000000f2001"
DESK_CRON="${DESK_CRON_SECRET:-starreply-desk-cron-secret}"

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
MAILPIT="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["MAILPIT_URL"])')"
echo "api $API_URL"

say "schema, rls, trigger"
for f in 01-schema.sql 04-auth-events.sql 03-rls.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/starreply-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f "/tmp/starreply-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# ⛔ RULE 10. auth.users is shared by every environment on this stack, and ONE null token column
# anywhere in it makes GoTrue's admin list-users answer 500 for every caller. The dispatcher's own
# claimDue() calls listUsers to find the demo account, so a 500 is a silent wrong answer far away
# from its cause. Repair first, then probe.
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

say "fixture auth user"
code=$(curl -s -o /tmp/starreply-desk-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
  -d "{\"id\":\"$USER_ID\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"email_confirm\":true,\"user_metadata\":{\"company\":\"Bloomwell Dental Group\"}}")
case "$code" in
  200|201) echo "created $EMAIL" ;;
  422) echo "already exists" ;;
  *) echo "unexpected $code: $(cat /tmp/starreply-desk-user.json)" >&2; exit 1 ;;
esac

probe=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE")
[ "$probe" = "200" ] || { echo "admin list-users answered $probe, not 200 (rule 10)" >&2; exit 1; }
echo "admin list-users $probe"

# The fixture's foreign keys resolve only once the auth user exists, so the seed runs after it.
say "fixture"
docker cp "$HERE/sql/02-seed.sql" "$DB:/tmp/starreply-02-seed.sql" >/dev/null
docker exec "$DB" psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q -f /tmp/starreply-02-seed.sql
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
# Rule 9's other half: a build older than its source is the wrong bytes, and the
# server started from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$HERE/app" "$API_URL" "$PORT"
cd "$HERE/app"
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" CRON_SECRET="$DESK_CRON" \
       NEXT_PUBLIC_APP_URL="http://127.0.0.1:$PORT" NEXT_PUBLIC_SITE_URL="http://127.0.0.1:$PORT"
[ -d node_modules ] || npm ci --no-audit --no-fund
# ⛔ PRODUCTION BUILD, NEVER THE DEV SERVER. Rule 6: a broken hydration in dev leaves React
# handlers unbound, so every control on the console does nothing and nothing errors.
[ -d .next ] || npm run build
echo "built"

desk_stamp_build "$HERE/app" "$API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # Detached. Backgrounded with a plain ampersand the server belongs to this script's process
  # group, so whatever called up.sh takes the server down with it when it exits.
  nohup npm start >/tmp/starreply-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/starreply-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/starreply-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
DESK_MAILPIT_URL="$MAILPIT" node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  mailpit $MAILPIT"
echo "  prove   uv run python envs/starreply-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py starreply-desk"
