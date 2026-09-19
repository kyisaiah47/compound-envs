#!/usr/bin/env bash
# Bring agentwire-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, a fixture LANE the product's mirror reads, an app copy built against
# the LOCAL stack, and Agentwire on 3741. Safe to re-run: every step either does nothing or
# does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This never starts one, never creates a
# second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds Agentwire's three tables to it.
#
# ⛔ THE APP IS BUILT IN envs/agentwire-desk/app, NEVER IN ~/CompoundLabs/agentwire (rules 9
# and 12). NEXT_PUBLIC_SUPABASE_URL is inlined at build time, and more to the point this app
# reads public.agentwire_posts through the SERVICE ROLE on the server, so a build carrying the
# production url would serve the production index and write the production list. Building a
# copy also keeps the product tree clean, which the 00:30 deploy sweep requires.
#
# ⛔ WHAT IS DELIBERATELY NOT SET, AND WHY EACH ONE MATTERS ON THIS PRODUCT:
#   RESEND_API_KEY      absent. src/lib/email.ts logs and returns null before it opens a
#                       socket, so `POST /api/subscribe` runs its own unconfigured path and
#                       nothing can send real mail. The firewall refuses api.resend.com too.
#   REVALIDATE_SECRET   absent. scripts/mirror-posts.mjs has
#                       SITE_URL = 'https://agentwire.thecompound.tech' HARDCODED and POSTs
#                       /api/revalidate to it after a successful write. Unset, the script says
#                       it cannot purge and makes no request. The firewall refuses that host
#                       as well, so a bring-up here can never touch the live site.
#   every model key     absent. Agentwire makes no model call on any route. scripts/gen-index.mjs
#                       does (two per bare row, to find a picture) and is NEVER run here.
#
# ⛔ WHAT IS SET, AND IS NOT WHAT IT LOOKS LIKE:
#   CRON_SECRET is a fixture string and nothing else. It gates GET /api/digest-items, which
#   renders the day's digest and WRITES NOTHING, so it is in not_gradable rather than a task.
#   It is set so that route answers rather than 401ing by accident.
#
# ⛔ AND THE ONE THIRD PARTY THIS PRODUCT CANNOT RUN WITHOUT IS STUBBED, NOT REFUSED.
#   src/lib/email-render.ts posts to the PRODUCTION project's email-render edge function
#   before sendEmail() ever looks for a key. harness/no-outbound.mjs answers that one url
#   offline in the shape renderTemplate() asserts, so the subscribe route runs its real
#   healthy path with no packet leaving this machine and no dependency on a third party
#   being up. Everything else outbound is refused.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${DESK_APP_DIR:-$HOME/CompoundLabs/agentwire}"
LANE_SRC="${DESK_LANE_DIR:-$HOME/CompoundLabs/compound-ops/social/agentwire}"
APP="$HERE/app"
LANE="$HERE/lane"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3741}"
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
# ⛔ 02-seed.sql NEVER TRUNCATES. It deletes by this fixture's own prefix only, so an
# agentwire_* row belonging to anything else on this shared stack survives a bring-up here.
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/agentwire-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/agentwire-$f" 2>&1 \
    | grep -vE "NOTICE|already exists|setval|^-+$|^\s*$|^\(1 row\)$" || true
  echo "applied $f"
done

# ⛔ RULE 10. One NULL token column anywhere in the SHARED auth.users 500s admin list-users for
# every environment on this stack, and a product reads that 500 as "there is no demo account".
# Agentwire has no accounts at all (src/lib/supabase.ts carries ONE client, the service role
# one, and says so), so it cannot cause this and cannot be hurt by it. The repair still runs,
# because this environment shares the table with the ones that do, and leaving a neighbour
# broken is the same as breaking it.
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

say "row security, measured rather than assumed"
# There is no sign-in anywhere in this product, so these two lines are the ONLY thing between
# the publishable key and a table of people's email addresses. Both are read off the running
# stack with the key a browser would hold.
idx=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/agentwire_posts?select=slug&limit=1" \
      -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
lst=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/agentwire_subscribers?select=email&limit=1" \
      -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
snd=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/agentwire_email_sends?select=email&limit=1" \
      -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
echo "agentwire_posts -> $idx (200 expected), agentwire_subscribers -> $lst, agentwire_email_sends -> $snd"
[ "$idx" = "200" ] || { echo "the public index does not read; the site would render its static fallback" >&2; exit 1; }
rows=$(curl -s "$API_URL/rest/v1/agentwire_subscribers?select=email" \
       -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
case "$rows" in
  '[]'|*'permission denied'*|*'"code"'*) echo "the subscriber list is shut to the publishable key" ;;
  *) echo "the publishable key can read subscriber addresses; refusing to continue" >&2; exit 1 ;;
esac

say "the fixture lane the mirror reads"
# ⛔ THE LANE CODE IS COPIED FROM THE REAL LANE, NEVER REWRITTEN. scripts/mirror-posts.mjs
# imports postedClaims() and keyOf() out of the lane's own queue.mjs, and queue.mjs imports
# poll.mjs, which reads sources.json at module load. Reimplementing any of the three would
# mean grading a stub instead of the product's own derivation, which is rule 1 with the
# wrapper on the outside.
#
# ⛔ AND NOTHING HERE POLLS ANYTHING. postedClaims() calls syncClaims(), which only re-reads
# claims.json off disk; pollAgentwire(), the function that talks to GitHub and Hacker News,
# is never called and writes seen.json only from inside itself. The ledger below is entirely
# fabricated, so this environment never depends on what some feed published this morning.
[ -d "$LANE_SRC" ] || { echo "lane not found at $LANE_SRC (set DESK_LANE_DIR)" >&2; exit 1; }
mkdir -p "$LANE"
for f in queue.mjs poll.mjs sources.json; do
  cp "$LANE_SRC/$f" "$LANE/$f"
done
cp "$HERE/fixture/claims.json" "$LANE/claims.json"
cp "$HERE/fixture/posted.jsonl" "$LANE/posted.jsonl"
printf '{}' > "$LANE/seen.json"
node -e '
  const { pathToFileURL } = require("node:url");
  import(pathToFileURL(process.argv[1]).href).then((m) => {
    const posted = m.postedClaims();
    const keys = new Set(posted.map((p) => p.key));
    if (posted.length !== 3 || keys.size !== 2) {
      console.error(`the fixture ledger reads ${posted.length} send(s) over ${keys.size} repo(s); expected 3 over 2`);
      process.exit(1);
    }
    console.log(`lane ready: ${posted.length} posted send(s) over ${keys.size} repo(s), 1 claim never posted`);
  }).catch((e) => { console.error("the lane copy does not load: " + e.message); process.exit(1); });
' "$LANE/queue.mjs"

say "app copy"
# ⛔ THE PRODUCT'S OWN .env.local IS EXCLUDED, AND THAT IS THE WHOLE POINT OF RULE 9. It holds
# the PRODUCTION Supabase url and service role key, the live Resend key and CRON_SECRET.
# Copied in, even for the moment before the block below overwrites it, that is a production
# service role key sitting in this tree one skipped step away from being the client this app
# writes through. Same for .vercel and .wrangler.
CHANGED="$(rsync -a --delete --itemize-changes \
      --exclude node_modules --exclude .next --exclude .open-next \
      --exclude .git --exclude .vercel --exclude .wrangler \
      --exclude '.env*' --exclude tsconfig.tsbuildinfo \
      "$APP_SRC"/ "$APP"/ | grep -vcE '^$|^\.d\.\.t\.+ \./$' || true)"
# The bare `./` line rsync always prints for the destination directory's own mtime is dropped:
# left in, CHANGED is never 0 and every bring-up rebuilds whether or not anything moved.
echo "copied to $APP ($CHANGED paths changed)"

cd "$APP"
cat > .env.local <<EOF
NEXT_PUBLIC_SUPABASE_URL=$API_URL
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
NEXT_PUBLIC_SITE_URL=http://127.0.0.1:$PORT
CRON_SECRET=agentwire-desk-fixture-cron-secret-not-a-real-one
EOF
[ -d node_modules ] || npm ci --no-audit --no-fund

say "app build"
# ⛔ RULE 9, BOTH HALVES. A build older than its source is the wrong bytes, and a server
# started from it keeps serving them.
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
REBUILT=0
if [ ! -d .next ] || [ "$CHANGED" -gt 0 ]; then
  # ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). Two of the four tasks here are a
  # click on a page, and the dev server's hydration is exactly what makes a React handler
  # silently not fire.
  #
  # ⛔ AND THE BUILD IS FIREWALLED TOO. Next prerenders `/`, `/wire`, `/status` and the rest
  # through getItems(), which reads the local stack, and nothing in a build should be able to
  # reach anything else.
  NODE_OPTIONS="--import file://$HERE/harness/no-outbound.mjs" npm run build
  REBUILT=1
fi
desk_stamp_build "$APP" "$API_URL"
echo "built"

say "app"
# A REBUILD WITHOUT A RESTART SERVES THE OLD BUNDLE. `next start` reads .next once, at boot.
#
# ⛔ AND A RESEED WITHOUT A RESTART SERVES THE OLD INDEX. src/lib/posts.ts wraps the table read
# in unstable_cache on a 3600s window and every page renders through it, so a page rendered
# before 02-seed.sql ran keeps its rows for an hour. The seed runs above on every bring-up, so
# the server is taken down on every bring-up too. This is the same class of failure rule 9
# describes, with the stale bytes in a cache rather than in .next.
if [ -f /tmp/agentwire-desk-app.pid ]; then
  kill "$(cat /tmp/agentwire-desk-app.pid)" 2>/dev/null || true
  sleep 2
fi
pids="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
for pid in $pids; do kill "$pid" 2>/dev/null || true; done
[ -n "$pids" ] && sleep 2
# ⛔ DETACHED. Backgrounded with a plain `&` the server belongs to this script's process group,
# so whatever called up.sh takes the server down with it when it exits.
# ⛔ AND BEHIND THE OUTBOUND FIREWALL. See the header: the mailer renders remotely BEFORE it
# checks for a key, so "no Resend key" alone does not keep this environment offline.
NODE_OPTIONS="--import file://$HERE/harness/no-outbound.mjs" \
  nohup npm start >/tmp/agentwire-desk-app.log 2>&1 &
APP_PID=$!
disown "$APP_PID" 2>/dev/null || true
echo "$APP_PID" > /tmp/agentwire-desk-app.pid
for _ in $(seq 1 60); do
  curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
  sleep 1
done
echo "started on $PORT (pid $APP_PID, log /tmp/agentwire-desk-app.log)"

say "what the pages are actually rendering (rule 2)"
# ⛔ THIS IS MEASURED, NOT ASSUMED, AND IT IS THE CHECK THAT MATTERS MOST ON THIS PRODUCT.
# src/lib/posts.ts reads public.agentwire_posts live and FALLS BACK to the committed manifest
# src/data/posts.json when the read fails or comes back empty. The manifest holds 100+ real
# production entries. A broken key, a missing table or an RLS surprise therefore does not
# error: the site renders PRODUCTION's index against this fixture's database and every id on
# screen names a row that does not exist here. That is the frozen-capture failure the wire
# environments already paid for, in a different shape.
# The index is the ROOT route. There is no /wire page: next.config.ts 308s /wire to /, and the
# only thing under /wire is the per entry page /wire/[slug]. Measured, because an up.sh that
# probes a redirect for a string finds nothing and reports the fallback that is not happening.
body="$(curl -s -m 20 "http://127.0.0.1:$PORT/")"
echo "$body" | grep -q 'awdesk-forge' \
  || { echo "/ does not carry a fixture entry: the page is rendering the static fallback, not this database" >&2; exit 1; }
entry="$(curl -s -o /dev/null -w '%{http_code}' -m 20 "http://127.0.0.1:$PORT/wire/awdesk-forge-relaypost-197a96")"
[ "$entry" = "200" ] || { echo "the fixture entry page answered $entry; getItemForArticle is not reading this database" >&2; exit 1; }
echo "/ carries the fixture's own entries, and its entry page answers 200"

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app        http://127.0.0.1:$PORT"
echo "  index      http://127.0.0.1:$PORT/   (there is no /wire page; it 308s here)"
echo "  confirm    http://127.0.0.1:$PORT/api/subscribe/confirm?token=00000000-0000-4000-8000-0000000f9701"
echo "  unsub      http://127.0.0.1:$PORT/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-0000000f9703"
echo "  prove      uv run python envs/agentwire-desk/adversarial/prove_graders.py"
