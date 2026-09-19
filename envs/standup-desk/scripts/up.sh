#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, fixture, RLS, the auth trigger, an isolated build of the app on 3745, and the harness's
# node modules. Safe to re-run: every step either does nothing or does the same thing again.
#
# THE APP IS NOT IN THIS REPO. standup is a separate tree and the environment builds it from
# there. Publishing this environment to someone who does not have that tree needs the app
# vendored or its image published; see PLAN.md.
#
# ONE SUPABASE STACK SERVES EVERY ENVIRONMENT IN THIS REPO, so this script does not start one.
# Every product in the estate shares one production project and they share one local stack too.
# If it is down, bring it up from the environment that owns the config and re-run this.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${STANDUP_APP_DIR:-$HOME/CompoundLabs/standup}"
APP="$HERE/app"
STACK_DIR="${STANDUP_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${STANDUP_DB_CONTAINER:-supabase_db_stack}"
PORT="${STANDUP_APP_PORT:-3745}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_SRC" ] || { echo "app tree not found at $APP_SRC (set STANDUP_APP_DIR)" >&2; exit 1; }

say "supabase stack"
docker ps --format '{{.Names}}' | grep -qx "$DB" || {
  echo "the shared local stack is not running." >&2
  echo "start it once from the environment that owns the config:  (cd $STACK_DIR && supabase start)" >&2
  exit 1
}
echo "running"

# Read the keys off the running stack rather than hardcoding them: they are per-project and a
# stale copy here would fail as an auth error somewhere far away from its cause.
say "keys"
STATUS="$(cd "$STACK_DIR" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
ANON="$(echo "$STATUS"   | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS"| python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, trigger, rls, fixture"
for f in 01-schema.sql 04-auth-trigger.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/$f" 2>&1 \
    | grep -vE "NOTICE|already exists|skipping" || true
  echo "applied $f"
done

# THE APP IS BUILT FROM A COPY, NOT IN PLACE, and that is not tidiness.
# Next inlines every NEXT_PUBLIC_ value into the SERVER bundle at build time, so a `.next` built
# against production points this product's API routes at the production database no matter what
# is in the environment at `npm start`. The product tree already carries such a build and an
# in-place rebuild would replace it with a localhost one. Neither direction is acceptable, so the
# source is copied out (without .env.local, whose values would override these) and built here.
say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude '.next' --exclude '.next-build' --exclude '.open-next' \
  --exclude '.git' --exclude '.vercel' --exclude '.wrangler' --exclude '.env*' \
  --exclude 'design-reviews' --exclude 'tsconfig.tsbuildinfo' \
  "$APP_SRC/" "$APP/"
ln -sfn "$APP_SRC/node_modules" "$APP/node_modules"
echo "copied from $APP_SRC"

say "app build"
cd "$APP"
export NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_ANON_KEY="$ANON" \
       SUPABASE_SERVICE_ROLE_KEY="$SERVICE" \
       NEXT_PUBLIC_SITE_URL="http://127.0.0.1:$PORT" \
       CRON_SECRET="standup-desk-cron" REVALIDATE_SECRET="standup-desk-revalidate"
[ -d .next ] || npm run build
# Read back what was actually inlined. A build that does not carry the local API url is a build
# whose routes are pointed somewhere else, and nothing downstream would say so.
grep -rql "$(echo "$API_URL" | sed 's#https\?://##')" .next/server/app/api/subscribe/route.js \
  || { echo "the build does not carry $API_URL: it was built against another stack" >&2; exit 1; }
echo "built, wired to $API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/sign-in"; then
  echo "already serving on $PORT"
else
  # DETACHED, AND THAT IS NOT DECORATION. Backgrounded with a plain `&` the server belongs to
  # this script's process group, so whatever called up.sh takes the server down with it when it
  # exits. nohup plus disown detaches it from both.
  nohup npm start >/tmp/standup-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/standup-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/sign-in" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/standup-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
echo "ready"

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  studio  $(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["STUDIO_URL"])')"
echo "  prove   uv run python envs/standup-desk/adversarial/prove_graders.py"
echo "  rollout node envs/standup-desk/harness/rollout.mjs subscribe"
echo "          node envs/standup-desk/harness/rollout.mjs signup"
