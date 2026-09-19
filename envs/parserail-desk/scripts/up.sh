#!/usr/bin/env bash
# Bring parserail-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, functions, RLS, fixture, both auth users, an app copy built against the LOCAL stack on
# 3769, and a captured session. Safe to re-run: every step either does nothing or does the same
# thing again.
#
# ⛔ THE PRODUCT TREE IS READ, NEVER WRITTEN, AND NEVER BUILT IN PLACE (rules 9 and 12).
# The app is rsync'd into envs/parserail-desk/app (gitignored) and built THERE, with .env* excluded
# so the product's own file cannot come along. That file carries a live STRIPE_SECRET_KEY and the
# production Supabase url, and NEXT_PUBLIC_* is inlined at BUILD time: reusing the product's .next,
# or copying its env, would serve the production anon key to the browser and open real sessions
# against the live project.
#
# ⛔ NO MODEL-PROVIDER KEY IS SET, ON PURPOSE. Every /v1 capability resolves its rail through
# @compound/integrations, whose registry falls back to the graceful stub when no key is configured,
# so nothing in this environment can spend ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY.
# The tasks are written against writes the product makes with no inference at all.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/parserail}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3769}"

OPERATOR_ID="00000000-0000-4000-8000-0000000f3001"
OPERATOR_EMAIL="${DESK_EMAIL:-ops@lindmark-freight.example}"
DEV_B_ID="00000000-0000-4000-8000-0000000f3002"
DEV_B_EMAIL="dev@verrazano-imports.example"
PASSWORD="${DESK_PASSWORD:-parserail-fixture-password}"

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

say "schema, functions, rls, fixture"
for f in 01-schema.sql 04-functions.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/parserail-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/parserail-$f" \
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
# ⛔ 0f3001 and 0f3002 are this environment's namespace in the SHARED auth.users (rule 11).
# Nothing else on this stack may hold them; picking a colliding uuid fails on users_pkey and the
# second environment to run its up.sh is the one that discovers it.
mkuser() {
  local id="$1" email="$2" company="$3"
  local code
  code=$(curl -s -o /tmp/parserail-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
    -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$id\",\"email\":\"$email\",\"password\":\"$PASSWORD\",\"email_confirm\":true,\"user_metadata\":{\"company\":\"$company\"}}")
  case "$code" in
    200|201) echo "created $email" ;;
    422)     echo "already exists: $email" ;;
    *)       echo "unexpected $code for $email: $(cat /tmp/parserail-user.json)" >&2; exit 1 ;;
  esac
}
mkuser "$OPERATOR_ID" "$OPERATOR_EMAIL" "Lindmark Freight"
mkuser "$DEV_B_ID" "$DEV_B_EMAIL" "Verrazano Imports"

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' \
  --exclude '.env' --exclude '.env.*' \
  "$SRC"/ "$APP"/
cat > "$APP/.env.local" <<ENVFILE
# Written by envs/parserail-desk/scripts/up.sh. The product's own .env.local is excluded from the
# rsync: it names the PRODUCTION Supabase project and carries a live STRIPE_SECRET_KEY.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$ANON
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
NEXT_PUBLIC_APP_URL=http://127.0.0.1:$PORT
NEXT_PUBLIC_WEB_URL=http://127.0.0.1:$PORT
CRON_SECRET=parserail-desk-cron-fixture
# No ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY, and no STRIPE_SECRET_KEY. Inference
# resolves to the graceful stub and payments to the payments stub, so no rollout can spend.
ENVFILE
echo "copied to $APP"

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the
# server started from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
cd "$APP"
[ -d node_modules ] || npm ci --silent --no-audit --no-fund
[ -d .next ] || npm run build
echo "built"

desk_stamp_build "$APP" "$API_URL"

say "app"
if curl -s -o /dev/null -m 3 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # Detached with nohup + disown: backgrounded with a plain & the server belongs to this
  # script's process group and dies with whatever called up.sh.
  nohup npm start >/tmp/parserail-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/parserail-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/parserail-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
DESK_API_URL="$API_URL" DESK_ANON_KEY="$ANON" DESK_APP_URL="http://127.0.0.1:$PORT" \
DESK_EMAIL="$OPERATOR_EMAIL" DESK_PASSWORD="$PASSWORD" node signin.mjs

say "ready"
echo "  app     http://127.0.0.1:$PORT/dashboard"
echo "  prove   uv run python envs/parserail-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py parserail-desk"
