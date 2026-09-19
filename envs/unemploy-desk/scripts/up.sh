#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Stack, schema, fixture, RLS, storage bucket, the fixture's auth user, the app on 3773, and a
# captured session. Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ THE APP IS NOT IN THIS REPO. unemploy is a separate tree and the environment builds it from
# there. Publishing this environment to someone who does not have that tree needs the app
# vendored or its image published; see PLAN.md.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/unemploy}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3773}"
EMAIL="${DESK_EMAIL:-desk@brightlinefacilities.example}"
PASSWORD="${DESK_PASSWORD:-desk-fixture-password}"
USER_ID="00000000-0000-4000-8000-00000000000a"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_DIR" ] || { echo "app tree not found at $APP_DIR (set DESK_APP_DIR)" >&2; exit 1; }

say "supabase stack"
if ! docker ps --format '{{.Names}}' | grep -qx "$DB"; then
  (cd "$HERE/stack" && supabase start)
else
  echo "already running"
fi

# Read the keys off the running stack rather than hardcoding them: they are per-project and a
# stale copy here would fail as an auth error somewhere far away from its cause.
say "keys"
STATUS="$(cd "$HERE/stack" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, functions, rls, fixture"
for f in 01-schema.sql 04-auth-events.sql 03-rls.sql 02-seed.sql; do
  [ "$f" = "01-schema.sql" ] && docker exec "$DB" psql -U postgres -d postgres -tAc \
    "select 1 from information_schema.tables where table_name='cd_claims'" | grep -q 1 && {
      echo "skip $f (tables present)"; continue; }
  docker cp "$HERE/sql/$f" "$DB:/tmp/$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -f "/tmp/$f" 2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done
docker cp "$HERE/stack/supabase/migrations/20260919000002_cd_functions.sql" "$DB:/tmp/fn.sql" >/dev/null
docker exec "$DB" psql -U postgres -d postgres -q -f /tmp/fn.sql
echo "applied functions"

say "fixture auth user"
code=$(curl -s -o /tmp/desk-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
  -d "{\"id\":\"$USER_ID\",\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\",\"email_confirm\":true,\"user_metadata\":{\"company\":\"Brightline Facilities Group\"}}")
case "$code" in
  200|201) echo "created $EMAIL" ;;
  422) echo "already exists" ;;
  *) echo "unexpected $code: $(cat /tmp/desk-user.json)" >&2; exit 1 ;;
esac

say "app build"
cd "$APP_DIR"
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" \
       NEXT_PUBLIC_APP_URL="http://127.0.0.1:$PORT" NEXT_PUBLIC_WEB_URL="http://127.0.0.1:$PORT"
[ -d .next ] || npm run build
echo "built"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/sign-in"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED, AND THAT IS NOT DECORATION. Backgrounded with a plain `&` the server belongs to
  # this script's process group, so whatever called up.sh takes the server down with it when it
  # exits. That happened on 2026-09-19: the app was serving, the wrapper ended, and the port went
  # dead with nothing in any log to say why. nohup plus disown detaches it from both.
  nohup npm start >/tmp/unemploy-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/unemploy-desk-app.pid
  for _ in $(seq 1 30); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/sign-in" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/unemploy-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  mailpit $(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["MAILPIT_URL"])')"
echo "  prove   uv run python envs/unemploy-desk/adversarial/prove_graders.py"
echo "  rollout node envs/unemploy-desk/harness/rollout.mjs"
