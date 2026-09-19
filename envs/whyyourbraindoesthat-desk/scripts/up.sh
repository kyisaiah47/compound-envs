#!/usr/bin/env bash
# Bring whyyourbraindoesthat-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, an app copy built against the LOCAL stack, and the app on 3779. Safe to
# re-run: every step either does nothing or does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never starts one, never
# creates a second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds the publication tables to it.
#
# ⛔ THE APP IS BUILT IN envs/whyyourbraindoesthat-desk/app, NEVER IN
# ~/CompoundLabs/whyyourbraindoesthat (rules 9 and 12). The product's own .next would inline the
# PRODUCTION Supabase url and key, and this environment would quietly be writing reader addresses
# into the live list.
#
# ⛔ THE PRODUCT TREE IS STILL READ, AND THAT IS CORRECT. src/lib/corpus.mjs hardcodes
# `REPO = ~/CompoundLabs/whyyourbraindoesthat` and `scripts/derive.mjs` runs on `prebuild`, so the
# build reads the product's tokens, copy, manifesto, archive and mark out of the product tree. It
# READS. Nothing here writes into it, and no git command is run anywhere in this environment.
#
# ⛔ NO PAID KEY IS EVER SET, AND THE APP CANNOT REACH ONE.
#   * RESEND_API_KEY is absent. This app never sends mail: the weekly letter is sent by
#     compound-ops/letters/send-letter.py, which is a separate process this environment does not
#     run. See the README on why that lane is in `not_gradable`.
#   * STRIPE_SECRET_KEY is absent. The product's checkout route went with the quiz on 2026-09-14
#     and no route in this tree constructs a Stripe client.
#   * ANTHROPIC_API_KEY and OPENAI_API_KEY are absent and nothing in this product calls a model.
#   * AND THE SERVER RUNS BEHIND harness/no-outbound.mjs, preloaded with NODE_OPTIONS, which
#     refuses every server-side fetch that is not the local stack.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${DESK_APP_DIR:-$HOME/CompoundLabs/whyyourbraindoesthat}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3779}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"

# shellcheck source=/dev/null
. "$HERE/../../tools/stale-build.sh"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_SRC" ] || { echo "product tree not found at $APP_SRC (set DESK_APP_DIR)" >&2; exit 1; }

say "supabase stack"
docker ps --format '{{.Names}}' | grep -qx "$DB" \
  || { echo "the shared stack is not running; start it from envs/unemploy-desk/stack" >&2; exit 1; }
echo "already running"

say "keys"
STATUS="$(cd "$STACK" && supabase status -o json)"
API_URL="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["API_URL"])')"
PUBLISHABLE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["PUBLISHABLE_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/wybdesk-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/wybdesk-$f" 2>&1 \
    | grep -vE "NOTICE|already exists|setval|^-+$|^\s*$|^\(1 row\)$" || true
  echo "applied $f"
done

# ⛔ RULE 10. One NULL token column anywhere in the SHARED auth.users 500s admin list-users for
# every environment on this stack, and a product reads that 500 as "there is no demo account".
# This product has no accounts at all and never calls GoTrue, so it cannot cause this and cannot
# be hurt by it. The repair still runs, because leaving a neighbour broken is breaking it.
say "shared auth.users repair (rule 10)"
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
echo "admin list-users -> $code (200 expected)"

say "the reader list is shut to the browser"
# ⛔ MEASURED, NOT ASSUMED. sql/03-rls.sql leaves publication_subscribers with RLS on and no
# policy, which is production's own shape and the thing the subscribe route's header claims:
# "the table is unreadable from any browser". A policy accidentally created by any other
# environment on this shared stack would open the reader list, and nothing in the app would say
# so. The archive has to answer for the same reason, in the other direction.
#
# ⛔ THE MEASUREMENT IS THE BODY, NOT THE STATUS CODE, and the first cut of this check got that
# wrong and refused to continue on a correctly shut table. Supabase's local stack grants SELECT
# on every new public table to `anon`, so PostgREST does not answer 403: RLS with no policy
# simply filters every row away and it answers `200 []`. A status code cannot tell that apart
# from a table full of readers, which is why this reads what came back.
shut=$(curl -s "$API_URL/rest/v1/publication_subscribers?select=email" \
       -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
svc=$(curl -s "$API_URL/rest/v1/publication_subscribers?select=email" \
      -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE")
open=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/publication_posts?select=slug&limit=1" \
       -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
shutn=$(printf '%s' "$shut" | python3 -c 'import json,sys; d=sys.stdin.read(); print(len(json.loads(d)) if d.startswith("[") else -1)')
svcn=$(printf '%s' "$svc" | python3 -c 'import json,sys; d=sys.stdin.read(); print(len(json.loads(d)) if d.startswith("[") else -1)')
echo "publication_subscribers: publishable key sees $shutn addresses, service key sees $svcn; publication_posts -> $open"
[ "$shutn" = "0" ] || { echo "the publishable key can read the reader list ($shutn rows); refusing to continue" >&2; exit 1; }
[ "$svcn" -gt 0 ] 2>/dev/null || { echo "the service key reads no rows either, so the fixture did not land" >&2; exit 1; }
[ "$open" = "200" ] || { echo "the public archive read does not answer" >&2; exit 1; }

say "app copy"
# ⛔ THE PRODUCT'S OWN .env.local IS EXCLUDED, AND THAT IS THE WHOLE POINT OF RULE 9. It carries
# the PRODUCTION Supabase url, the production SERVICE ROLE key, a live Stripe secret and a live
# Resend key. Copied in, even for the moment before the block below overwrites it, the next
# `npm start` in this tree posts a reader address into the live list. Same for .vercel, which
# holds .env.production.local.
CHANGED="$(rsync -a --delete --itemize-changes \
      --exclude node_modules --exclude .next --exclude .open-next \
      --exclude .git --exclude .vercel --exclude .wrangler \
      --exclude '.env*' --exclude tsconfig.tsbuildinfo \
      --exclude shots --exclude design-reviews/redesign-2026-09-13/shots \
      "$APP_SRC"/ "$APP"/ | grep -vcE '^$|^\.d\.\.t\.+ \./$' || true)"
# The bare `./` line rsync always prints for the destination directory's own mtime is dropped:
# left in, CHANGED is never 0 and every bring-up rebuilds whether or not anything moved.
echo "copied to $APP ($CHANGED paths changed)"

cd "$APP"
# SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are the two the product reads, in both subscribe
# routes and in src/lib/live.ts. Nothing in this app is a NEXT_PUBLIC_ Supabase variable: the
# browser never talks to the database on this product, which is why the reader list can be shut.
cat > .env.local <<EOF
SUPABASE_URL=$API_URL
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
EOF
[ -d node_modules ] || npm ci --no-audit --no-fund

say "app build"
# ⛔ RULE 9, BOTH HALVES. A build older than its source is the wrong bytes, and a server started
# from it keeps serving them.
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
REBUILT=0
if [ ! -d .next ] || [ "$CHANGED" -gt 0 ]; then
  # ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). Both honest rollouts here are React
  # handlers: the letter form's onSubmit, and the confirm page's one submit button. A dev server
  # whose hydration breaks answers a click with nothing and the grader reads an empty table.
  npm run build
  REBUILT=1
fi
desk_stamp_build "$APP" "$API_URL"
echo "built"

say "app"
# A REBUILD WITHOUT A RESTART SERVES THE OLD BUNDLE. `next start` reads .next once, at boot.
if [ "$REBUILT" = 1 ] && [ -f /tmp/wyb-desk-app.pid ]; then
  kill "$(cat /tmp/wyb-desk-app.pid)" 2>/dev/null || true
  sleep 2
fi
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED. Backgrounded with a plain `&` the server belongs to this script's process group,
  # so whatever called up.sh takes the server down with it when it exits.
  NODE_OPTIONS="--import file://$HERE/harness/no-outbound.mjs" \
    nohup npm start >/tmp/wyb-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/wyb-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/wyb-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  door        http://127.0.0.1:$PORT/"
echo "  the letter  http://127.0.0.1:$PORT/#the-letter"
echo "  the way out http://127.0.0.1:$PORT/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-0000000fa001"
echo "  prove       uv run python envs/whyyourbraindoesthat-desk/adversarial/prove_graders.py"
