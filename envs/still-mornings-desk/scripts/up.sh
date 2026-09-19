#!/usr/bin/env bash
# Bring still-mornings-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, an app copy built against the LOCAL stack on 3777, a copy of the archive
# sync engine that lives outside the product repo, and the public storage bucket that sync
# uploads into. Safe to re-run: every step either does nothing or does the same thing again.
#
# NEITHER SOURCE TREE IS WRITTEN AND NEITHER IS BUILT IN PLACE (rules 9 and 12).
# `~/CompoundLabs/still-mornings` and `~/CompoundLabs/compound-ops/social/ugc` are read and
# rsync'd. `.env*` is excluded from the app copy, because the product's own `.env.local` names the
# PRODUCTION Supabase project, and NEXT_PUBLIC_* is inlined at BUILD time: reusing the product's
# `.next`, or letting its env file come along, serves production credentials to the browser.
#
# THE ENGINE COPY IS LAID OUT SO NOTHING IS PATCHED. publish.mjs resolves the product tree as
# `path.dirname(path.resolve(its own dir, '../..'))/<repo>`, so the copy goes to
# engine/social/ugc/publish.mjs and a SYMLINK `still-mornings -> app` beside it makes the product
# it finds this environment's own app copy. Its Supabase url and key come from the process
# environment, which it reads FIRST, so nothing about it needs editing. Proved below by importing
# nothing and instead running it and reading back which host the rows point at.
#
# NOTHING IN THIS ENVIRONMENT SPENDS A KEY OR SENDS ANYTHING. still-mornings reads no model API
# key anywhere in its tree and has no Stripe code. The one thing in its orbit that sends real mail
# is compound-ops/letters/send-letter.py, and this environment never runs it: see `not_gradable`
# in results.json and the README section on the letter.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/still-mornings}"
UGC_SRC="${DESK_UGC_SRC:-$HOME/CompoundLabs/compound-ops/social/ugc}"
OPS_SRC="${DESK_OPS_SRC:-$HOME/CompoundLabs/compound-ops}"
APP="$HERE/app"
ENGINE="$HERE/engine"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3777}"

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
  docker cp "$HERE/sql/$f" "$DB:/tmp/stillmornings-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/stillmornings-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# Rule 10. One NULL token column anywhere in the SHARED auth.users makes GoTrue's admin
# list-users answer 500 for EVERY caller on this stack, not just the broken row. still-mornings
# has no accounts and creates none, so this environment never needs that endpoint. It is repaired
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
# Rule 11: 00000000-0000-4000-8000-0000000fc001 upward is this environment's block in the shared
# auth.users. It is RESERVED AND UNUSED. still-mornings has no sign-in, no session, no account
# table and no auth import anywhere in its tree, so there is nothing for an auth user to be.
# Nothing else on this stack may take it.

say "storage bucket"
# publish.mjs uploads every picture a published entry points at into the public `publication`
# bucket and writes ABSOLUTE urls into the rows. Without the bucket every upload fails, the row
# falls back to the repo-relative path, and the sync task would grade a fallback.
curl -s -o /dev/null -X POST "$API_URL/storage/v1/bucket" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" \
  -H "Content-Type: application/json" \
  -d '{"id":"publication","name":"publication","public":true}' || true
have=$(curl -s "$API_URL/storage/v1/bucket/publication" \
  -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("id",""), d.get("public",""))')
[ "$have" = "publication True" ] || { echo "the publication bucket is not public: $have" >&2; exit 1; }
echo "bucket publication (public)"

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' --exclude shots \
  --exclude '.env' --exclude '.env.*' \
  "$SRC"/ "$APP"/
cat > "$APP/.env.local" <<ENVFILE
# Written by envs/still-mornings-desk/scripts/up.sh. The product's own .env.local is excluded from
# the rsync: it names the PRODUCTION Supabase project.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_ANON_KEY=$ANON
# Both write routes and src/lib/live.ts read this, and it is the ONLY key either needs.
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
ENVFILE
echo "copied to $APP"

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
  nohup npm start >/tmp/still-mornings-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/still-mornings-desk-app.pid
  for _ in $(seq 1 90); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/still-mornings-desk-app.log)"
fi

say "archive sync engine copy"
[ -d "$UGC_SRC" ] || { echo "ugc lane not found at $UGC_SRC (set DESK_UGC_SRC)" >&2; exit 1; }
mkdir -p "$ENGINE/social/ugc"
# Only the two files the sync is, plus the lane state the permalink lookup reads. The rest of that
# directory is the posting daemon, its queues and its captures, none of which this runs.
rsync -a "$UGC_SRC/publish.mjs" "$UGC_SRC/publication-dump.mts" "$ENGINE/social/ugc/"
mkdir -p "$ENGINE/social/ugc/daemon"
[ -f "$UGC_SRC/daemon/state.soft-life.json" ] \
  && cp -p "$UGC_SRC/daemon/state.soft-life.json" "$ENGINE/social/ugc/daemon/" || true
# publish.mjs computes PROJECTS as the parent of its own OPS root, then joins the repo name onto
# it. With the copy at engine/social/ugc, OPS is `engine` and PROJECTS is this environment, so the
# link below is what makes the product it opens the app copy rather than the real repo.
ln -sfn "$APP" "$HERE/still-mornings"
# tsx and @supabase/supabase-js, from the lane's own install. Read-only, never written.
ln -sfn "$OPS_SRC/node_modules" "$ENGINE/node_modules"
echo "engine at $ENGINE/social/ugc, product link -> $(readlink "$HERE/still-mornings")"

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "warm the storage ledger"
# The first sync uploads every frame a published entry points at; after that the ledger beside the
# script matches by content hash and the same run reuses them. Doing it here rather than inside a
# grader keeps the honest case a measurement of the write path and not of 300 uploads.
if [ ! -f "$ENGINE/social/ugc/.publication-uploads.json" ]; then
  ( cd "$ENGINE/social/ugc" && SUPABASE_URL="$API_URL" SUPABASE_SERVICE_ROLE_KEY="$SERVICE" \
      node publish.mjs still-mornings ) || {
    echo "the first sync failed; see the output above" >&2; exit 1; }
fi
# The seed clears only what this environment owns and then re-inserts it, so re-applying it puts
# the fixture back after the warm-up sync without touching another environment's rows.
docker cp "$HERE/sql/02-seed.sql" "$DB:/tmp/stillmornings-reseed.sql" >/dev/null
docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f /tmp/stillmornings-reseed.sql >/dev/null
echo "ledger warmed, fixture restored"

say "ready"
echo "  app     http://127.0.0.1:$PORT/"
echo "  prove   uv run python envs/still-mornings-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py still-mornings-desk"
