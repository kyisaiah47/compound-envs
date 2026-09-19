#!/usr/bin/env bash
# Bring stacktab-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, an app copy built against the LOCAL stack on 3318, the 28 fixture vendor
# pages the nightly reads, and a copy of the nightly engine pointed at the local stack.
# Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ NEITHER SOURCE TREE IS WRITTEN AND NEITHER IS BUILT IN PLACE (rules 9 and 12).
# `~/CompoundLabs/stacktab` and `~/CompoundLabs/compound-ops/lanes/stacktab/engine` are read and
# rsync'd. `.env*` is excluded from both copies, because the product's own `.env.local` names the
# PRODUCTION Supabase project and carries its service role key, and NEXT_PUBLIC_* is inlined at
# BUILD time: reusing the product's `.next`, or letting its env file come along, serves the
# production publishable key to the browser.
#
# ⛔ AND THE ENGINE IS THE REASON THAT MATTERS MORE HERE THAN ANYWHERE ELSE. `engine/db.mjs`
# resolves credentials by reading a hardcoded list of absolute paths, FILE FIRST and process
# environment last, so exporting SUPABASE_URL cannot redirect it. Run unpatched, from any
# directory, the nightly would re-check 29 real vendor pricing pages and write check_status,
# verified_at and a refresh_run row into PRODUCTION. The copy therefore has exactly two lines
# changed, both of them the path it reads credentials from, and this script proves that by
# diffing (exactly four changed lines) and then by importing the patched module and refusing to
# continue unless the URL it resolved is the local stack.
#
# ⛔ NOTHING IN THIS ENVIRONMENT SPENDS A KEY OR SENDS ANYTHING. stacktab reads no model API key
# anywhere in its tree (its own .env.example says so and a grep confirms it), has no Stripe code
# and no mail code. The one thing that leaves the machine in production is the footer's studio
# list capture, which posts to https://thecompound.tech/api/list/subscribe; the browser rollout
# addresses the price-watch control by its own id and never touches that form. See rule 7 in the
# README.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/stacktab}"
ENGINE_SRC="${DESK_ENGINE_SRC:-$HOME/CompoundLabs/compound-ops/lanes/stacktab/engine}"
APP="$HERE/app"
ENGINE="$HERE/engine"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3318}"

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
  docker cp "$HERE/sql/$f" "$DB:/tmp/stacktab-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/stacktab-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# Rule 10. One NULL token column anywhere in the SHARED auth.users makes GoTrue's admin
# list-users answer 500 for EVERY caller on this stack, not just the broken row. stacktab has no
# accounts and creates none, so this environment never needs that endpoint. It is repaired
# anyway: leaving a neighbour broken is the same as breaking it.
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
# Rule 11: 00000000-0000-4000-8000-0000000f6001 upward is this environment's block in the shared
# auth.users. It is RESERVED AND UNUSED. stacktab has no sign-in, no session and no account
# table, so there is nothing for an auth user to be. Nothing else on this stack may take it.

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' --exclude shots \
  --exclude '.env' --exclude '.env.*' --exclude '/public/vendor/' \
  "$SRC"/ "$APP"/
cat > "$APP/.env.local" <<ENVFILE
# Written by envs/stacktab-desk/scripts/up.sh. The product's own .env.local is excluded from the
# rsync: it names the PRODUCTION Supabase project and carries its service role key.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$ANON
SUPABASE_PUBLISHABLE_KEY=$ANON
# POST /api/watch is the only write in this product and it is the only thing that reads this.
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
# ⛔ NEVER 1. STACKTAB_FROZEN=1 renders data/stacktab/*.json instead of reading Supabase, so
# every page would show the captured production catalogue and no write would reach any row.
STACKTAB_FROZEN=0
ENVFILE

# The fixture's vendor pricing pages, served by the product's own static handler so the nightly
# has somewhere local to read. They go in BEFORE the build, or the staleness check sees public/
# change after it and rebuilds on every run.
# ⛔ `/public/vendor/` IS EXCLUDED FROM THE RSYNC ABOVE, AND THAT IS WHY. Without the exclude,
# --delete removes the directory and the mkdir below recreates it, which stamps `public` itself
# with the current time; `find public -newer .next/BUILD_ID` then matches the DIRECTORY and every
# bring-up discards a perfectly current build and restarts the server.
mkdir -p "$APP/public/vendor"
# -p keeps the generated pages' own mtimes. Without it every bring-up stamps public/ with the
# current time, the staleness check in tools/stale-build.sh correctly reads that as a changed
# source, and up.sh rebuilds and restarts the server on every single run.
cp -p "$HERE"/vendor-pages/*.html "$APP/public/vendor/"

# ⛔ NOTHING IS PATCHED IN THE APP COPY ANY MORE. Until 2026-09-19 this block turned
# `react/no-unescaped-entities` off in the copy's own eslint config, because a raw apostrophe in
# src/components/ListCapture.tsx:66 made `next build` stop at "Failed to compile" and the product
# could not build at all. That is fixed in the product (commit 5be206c, the apostrophe is
# `&apos;`), so the copy now builds exactly as the product does and this environment modifies
# none of it. See README, defect 1.
echo "copied to $APP ($(ls "$HERE"/vendor-pages/*.html | wc -l | tr -d ' ') vendor pages)"

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the server started
# from it keeps serving them. See tools/stale-build.sh.
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
  nohup npm start >/tmp/stacktab-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/stacktab-desk-app.pid
  for _ in $(seq 1 60); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/stacktab-desk-app.log)"
fi

say "nightly engine copy"
[ -d "$ENGINE_SRC" ] || { echo "engine not found at $ENGINE_SRC (set DESK_ENGINE_SRC)" >&2; exit 1; }
mkdir -p "$ENGINE"
rsync -a --delete --exclude node_modules --exclude '.env' --exclude '.env.*' \
  "$ENGINE_SRC"/ "$ENGINE"/
# The two credential paths, and nothing else.
sed -i '' "s|'$SRC/.env|'$ENGINE/.env|g" "$ENGINE/db.mjs"
changed=$(diff "$ENGINE_SRC/db.mjs" "$ENGINE/db.mjs" | grep -c '^[<>]' || true)
[ "$changed" = "4" ] || {
  echo "the engine patch changed $changed lines, expected 4 (two paths, in and out)" >&2; exit 1; }
diff "$ENGINE_SRC/db.mjs" "$ENGINE/db.mjs" | grep '^[<>]' | grep -qv '\.env' && {
  echo "the engine patch touched a line that is not a credential path" >&2; exit 1; } || true
cat > "$ENGINE/.env.local" <<ENVFILE
# Written by envs/stacktab-desk/scripts/up.sh. engine/db.mjs reads this FIRST and file values win
# over the process environment, which is why the copy is patched to look here rather than at the
# product's own .env.local, which names production.
SUPABASE_URL=$API_URL
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
ENVFILE
# Measured, not assumed: import the patched module and read back the URL it resolved.
resolved=$(cd "$ENGINE" && node -e "import('./db.mjs').then(m=>console.log(m.ENV.SUPABASE_URL))")
[ "$resolved" = "$API_URL" ] || {
  echo "the engine resolved $resolved, not $API_URL. Refusing to continue." >&2; exit 1; }
echo "engine points at $resolved"

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app     http://127.0.0.1:$PORT/"
echo "  prove   uv run python envs/stacktab-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py stacktab-desk"
