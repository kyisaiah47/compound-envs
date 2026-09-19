#!/usr/bin/env bash
# Bring thismuchweknow-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# It adds the publication tables to the SHARED Supabase stack, applies the RLS and the fixture,
# builds an app copy against that local stack and serves it on 3330.
# Safe to re-run: every step either does nothing or does the same thing again.
#
# THE PRODUCT TREE IS NEVER WRITTEN AND NEVER BUILT IN PLACE (rules 9 and 12).
# `~/CompoundLabs/thismuchweknow` is read and rsync'd. `.env*` is excluded from the copy: the
# product's own `.env.local` names the PRODUCTION Supabase project and carries its service role
# key, and POST /api/subscribe reads exactly those two variables. Building in place would also
# leave the product tree dirty, which costs it the 00:30 deploy.
#
# ⛔ THE BUILD IS THE PRODUCT'S OWN `npm run build` (rule 6, second half). This product's build
# script is `node scripts/build-inlined-files.mjs && next build`, and that first step regenerates
# `src/generated/inlined-files.ts`, which is what a Worker serves every phosphor glyph out of.
# `npx next build` skips it and compiles whatever that file happened to hold.
#
# NOTHING HERE SPENDS A KEY OR SENDS ANYTHING. This product reads no model API key anywhere:
# `grep -rhno "process\.env\.[A-Z_0-9]*" src/ scripts/ ops/` returns HOME, NEXT_PUBLIC_SUPABASE_URL,
# SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, and nothing else. There is no Stripe code and no mail
# code in the tree. The one thing in the estate that mails a publication's list is
# compound-ops/letters/send-letter.py, which does not name this publication at all, and this
# environment never runs it in any mode.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/thismuchweknow}"
OPS="${DESK_OPS_SRC:-$HOME/CompoundLabs/compound-ops}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3330}"

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
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/thismuchweknow-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/thismuchweknow-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# Rule 10. One NULL token column anywhere in the SHARED auth.users makes GoTrue's admin
# list-users answer 500 for EVERY caller on this stack, not just the broken row. This product has
# no sign-in and creates no account, so it never calls that endpoint. It is repaired anyway:
# leaving a neighbour broken is the same as breaking it.
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
# Rule 11: 00000000-0000-4000-8000-0000000fe001 upward is this environment's block in the shared
# auth.users. It is RESERVED AND UNUSED. This product has no sign-in, no session and no account
# table, so there is nothing for an auth user to be. Nothing else on this stack may take it. The
# uuids the fixture writes are unsub_tokens in `0000fe0N-`, which live in this product's own table.

say "wiring check"
# ⛔ THIS ENVIRONMENT HAS TWO TASKS AND NOT THREE BECAUSE OF THESE TWO FACTS, SO THEY ARE
# MEASURED RATHER THAN BELIEVED. The four sibling publications get a third task from the nightly
# sync that fills `publication_posts`. This publication is wired into neither end of that:
#
#   1. compound-ops/social/ugc/publish.mjs's SITES list names four repos and not this one, so
#      `node publish.mjs thismuchweknow` matches no site, writes nothing and exits 0.
#   2. this tree has no `src/lib/live.ts`, so nothing in it reads that table either. The archive
#      comes off `src/content/entries.json`, committed, at build time.
#
# If either changes, this check fails and this environment owes a third task rather than silently
# going on grading two.
if grep -q "repo: *'thismuchweknow'" "$OPS/social/ugc/publish.mjs" 2>/dev/null; then
  echo "publish.mjs now names this repo in SITES. The archive sync has become gradable and this" >&2
  echo "environment owes a third task. See the not_gradable entries in results.json." >&2
  exit 1
fi
if [ -f "$SRC/src/lib/live.ts" ]; then
  echo "$SRC/src/lib/live.ts now exists, so the product reads publication_posts at request time." >&2
  echo "That changes what an entry on a page is evidence of. Re-read rule 2 before grading." >&2
  exit 1
fi
echo "publish.mjs does not name this repo; the product has no live.ts. Two tasks, not three."

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' --exclude shots \
  --exclude '.env' --exclude '.env.*' \
  "$SRC"/ "$APP"/
cat > "$APP/.env.local" <<ENVFILE
# Written by envs/thismuchweknow-desk/scripts/up.sh. The product's own .env.local is excluded from
# the rsync: it names the PRODUCTION Supabase project and carries its service role key.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
SUPABASE_URL=$API_URL
# src/app/api/subscribe/route.ts reads SUPABASE_URL (falling back to NEXT_PUBLIC_SUPABASE_URL) and
# SUPABASE_SERVICE_ROLE_KEY. They are the only two variables the product uses.
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
# ⛔ `npm run build`, NEVER `npx next build`. See the header.
[ -d .next ] || npm run build
echo "built"
desk_stamp_build "$APP" "$API_URL"

say "app"
if curl -s -o /dev/null -m 3 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  nohup npm start >/tmp/thismuchweknow-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/thismuchweknow-desk-app.pid
  for _ in $(seq 1 90); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/thismuchweknow-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
# PUPPETEER_SKIP_DOWNLOAD, because harness/safe-chrome.mjs launches the SYSTEM Chrome by
# executablePath and never puppeteer's own bundled build. Without it the install fails on this
# machine: ~/.cache/puppeteer/chrome-headless-shell/mac_arm-148.0.7778.97 exists with its
# executable missing, so every provider reports the browser as installed and then cannot run it.
[ -d node_modules ] || PUPPETEER_SKIP_DOWNLOAD=true npm install --silent --no-audit --no-fund

say "ready"
echo "  app     http://127.0.0.1:$PORT/"
echo "  look    node harness/look.mjs"
echo "  prove   uv run python envs/thismuchweknow-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py thismuchweknow-desk"
