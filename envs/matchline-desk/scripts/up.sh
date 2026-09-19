#!/usr/bin/env bash
# Bring matchline-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, the ml-files bucket with both delivered PDFs in it, an app copy built
# against the LOCAL stack, and the app on 3300. Safe to re-run: every step either does nothing
# or does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never starts one, never
# creates a second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds MatchLine's two tables to it.
#
# ⛔ THE PRODUCT TREE IS READ, NEVER WRITTEN, AND NEVER BUILT IN PLACE (rules 9 and 12). The app
# is rsync'd into envs/matchline-desk/app (gitignored) and built THERE, with .env* excluded so
# the product's own file cannot come along. ~/CompoundLabs/matchline/.env.local carries the
# PRODUCTION Supabase project and a LIVE Stripe secret key, and NEXT_PUBLIC_* is inlined at BUILD
# time: reusing the product's .next, or copying its env, would serve the production publishable
# key to the browser and this environment would quietly be driving the live project.
#
# ⛔ NO STRIPE KEY IS SET, AND THAT IS THE STRICTER READING OF "USE A PLACEHOLDER".
# MatchLine bills on the SECOND live Stripe key on this machine, the one OutRip and WireCall use
# (the account id is measured and written into the product's own .env.example). A
# placeholder key is not inert: constructing a Stripe client with one succeeds perfectly happily
# and the first call goes out over the wire to api.stripe.com to be refused there. Leaving the
# variable ABSENT is what makes an outbound call impossible, and it is also the product's own
# not-configured path: src/lib/stripe.ts throws `STRIPE_SECRET_KEY is not set.` before any
# network call exists. That is the path this environment runs, and it is why
# POST /api/checkout and GET /api/checkout/confirm are recorded as not gradable in results.json
# rather than dressed up as tasks.
#
# ⛔ NO MODEL KEY IS SET EITHER, and none is needed. Every model call MatchLine makes is in
# ops/worker.mjs, a launchd loop on this machine that runs on the subscription CLI. No route in
# src/app/api touches a model at all. Nothing here can spend ANTHROPIC_API_KEY or OPENAI_API_KEY.
#
# ⛔ NOTHING SENDS MAIL. The only mailer is ops/mail/send_tailored.py, called by the worker,
# which this environment never starts. RESEND_API_KEY is not set.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/matchline}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3300}"

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
PUBLISHABLE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["PUBLISHABLE_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/matchline-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/matchline-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# Rule 10. One NULL token column anywhere in the SHARED auth.users makes GoTrue's admin
# list-users answer 500 for EVERY caller on this stack, not just the broken row. MatchLine has
# no accounts at all and never calls GoTrue, so it cannot cause this and cannot be hurt by it.
# The repair still runs, because this environment shares the table with the ones that can be,
# and leaving a neighbour broken is the same as breaking it.
say "shared auth.users token repair (rule 10)"
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

# ⛔ RULE 11, and MatchLine's answer to it is "none needed". The product is anonymous end to
# end: no sign-in, no session, no user_id column on either table. 00000000-0000-4000-8000-
# 0000000f7001 upward is still reserved for matchline-desk in the SHARED auth.users so nothing
# else on this stack claims the block, and the fixture's own row ids (…0f70xx) come out of it.
echo "auth users: none (matchline has no accounts); block 0f7001+ reserved"

say "the ml-files bucket"
MATCHLINE_DESK_API_URL="$API_URL" MATCHLINE_DESK_SERVICE_KEY="$SERVICE" \
  python3 -c "
import sys; sys.path.insert(0, '$HERE')
from matchline_desk import store
store.restore()
print('restored', ', '.join(store.SEEDED_PDFS))
"

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' \
  --exclude '.env' --exclude '.env.*' \
  "$SRC"/ "$APP"/
cat > "$APP/.env.local" <<ENVFILE
# Written by envs/matchline-desk/scripts/up.sh. The product's own .env.local is excluded from
# the rsync: it names the PRODUCTION Supabase project and carries a LIVE Stripe secret key.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$PUBLISHABLE
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
# No STRIPE_SECRET_KEY: src/lib/stripe.ts then throws before any request to api.stripe.com can
# be built, which is the only way to guarantee this environment never reaches Stripe.
# No ANTHROPIC_API_KEY, OPENAI_API_KEY or GEMINI_API_KEY: no route in this app calls a model.
# No RESEND_API_KEY: the only mailer is ops/worker.mjs, which this environment never starts.
ENVFILE
echo "copied to $APP"

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the server started
# from it keeps serving them no matter what gets built next. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
cd "$APP"
[ -d node_modules ] || npm ci --silent --no-audit --no-fund
# ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). The one browser task here is a click on
# a React handler, and a broken dev-server hydration is exactly what makes that click do nothing
# while every page still renders.
[ -d .next ] || npm run build
echo "built"
desk_stamp_build "$APP" "$API_URL"

say "app"
if curl -s -o /dev/null -m 3 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # Detached with nohup + disown: backgrounded with a plain & the server belongs to this
  # script's process group and dies with whatever called up.sh.
  nohup npm start >/tmp/matchline-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/matchline-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/matchline-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app     http://127.0.0.1:$PORT/"
echo "  prove   uv run python envs/matchline-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py matchline-desk"
