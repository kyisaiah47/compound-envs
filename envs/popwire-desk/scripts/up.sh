#!/usr/bin/env bash
# Bring popwire-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, a fixture LANE the product's mirror reads, an app copy built against
# the LOCAL stack, and Popwire on 3747. Safe to re-run: every step either does nothing or
# does the same thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This never starts one, never creates a
# second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds Popwire's tables to it.
#
# ⛔ THE APP IS BUILT IN envs/popwire-desk/app, NEVER IN ~/CompoundLabs/popwire (rules 9 and
# 12). NEXT_PUBLIC_SUPABASE_URL is inlined at build time, and more to the point this app
# reads and writes public.popwire_* through the SERVICE ROLE on the server, so a build
# carrying the production url would serve the production index and write the production
# list. Building a copy also keeps the product tree clean, which the 00:30 deploy sweep
# requires. Measured 2026-09-19: ~/CompoundLabs/popwire/src/data/posts.json is dirty from
# another actor, this script only READS that tree, and nothing here runs git.
#
# ⛔ WHAT IS DELIBERATELY NOT SET, AND WHY EACH ONE MATTERS ON THIS PRODUCT:
#   RESEND_API_KEY   absent. src/lib/email.ts logs and returns null before it opens a
#                    socket, so POST /api/subscribe runs its own unconfigured path and
#                    nothing can send real mail. The firewall refuses api.resend.com too.
#   CRON_SECRET      absent. GET /api/digest-items answers 401 on its own first branch. The
#                    route renders the digest and WRITES NOTHING, so it is in not_gradable
#                    rather than a task, and leaving the secret unset keeps the one route
#                    that renders an email through a third party out of every code path
#                    this environment exercises.
#   every model key  absent. Popwire makes no model call on any route or in any script it
#                    ships. The lane's harvest and write steps do, and neither is run here.
#
# ⛔ AND THE THREE THIRD PARTIES THIS PRODUCT CANNOT RUN WITHOUT ARE STUBBED, NOT REFUSED.
#   harness/no-outbound.mjs answers the production email-render edge function, the account's
#   Bluesky author feed and the Bluesky image CDN offline, from envs/popwire-desk/fixture.
#   Everything else outbound is refused. See that file's header for why a refusal is the
#   wrong answer for each of them.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${DESK_APP_DIR:-$HOME/CompoundLabs/popwire}"
APP="$HERE/app"
LANE_HOME="$HERE/lanehome"
LANE="$LANE_HOME/CompoundLabs/compound-ops/social/popwire"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3747}"
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
ANON="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ANON_KEY"])')"
SERVICE="$(echo "$STATUS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["SERVICE_ROLE_KEY"])')"
echo "api $API_URL"

say "schema, rls, fixture"
# ⛔ 02-seed.sql NEVER TRUNCATES. popwire_posts is shared with wirecall-desk, which seeds six
# `wcdesk-%` rows in it, and social_posts is the estate-wide posting ledger. The seed deletes
# `marrowgate-%` and `app = 'popwire'` and nothing else.
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/popwire-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/popwire-$f" 2>&1 \
    | grep -vE "NOTICE|already exists|setval|^-+$|^\s*$|^\(1 row\)$" || true
  echo "applied $f"
done

# ⛔ RULE 10. One NULL token column anywhere in the SHARED auth.users 500s admin list-users
# for every environment on this stack, and a product reads that 500 as "there is no demo
# account". Popwire has no accounts at all: src/lib/supabase.ts exports supabaseBrowser() and
# NOTHING in the tree calls it, so this product cannot cause that failure and cannot be hurt
# by it. The repair still runs, because this environment shares the table with the ones that
# can, and leaving a neighbour broken is the same as breaking it.
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
# There is no sign-in anywhere in this product, so these four lines are the ONLY thing between
# the publishable key and a table of people's email addresses. All four are read off the
# running stack with the key a browser would hold.
idx=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/popwire_posts?select=slug&limit=1" \
      -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
echo "popwire_posts -> $idx (200 expected)"
[ "$idx" = "200" ] || { echo "the public index does not read; the site would render its static fallback" >&2; exit 1; }
for t in popwire_subscribers popwire_email_sends social_posts; do
  rows=$(curl -s "$API_URL/rest/v1/$t?select=*&limit=1" \
         -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
  case "$rows" in
    '[]'|*'permission denied'*|*'"code"'*) echo "$t is shut to the publishable key" ;;
    *) echo "the publishable key can read $t; refusing to continue" >&2; exit 1 ;;
  esac
done

say "the card the roof story already shipped with"
# ⛔ THROUGH THE STORAGE API, BECAUSE SQL CANNOT PUT BYTES IN A BUCKET. The seeded roof row
# carries an img and a thumb naming two objects in the `popwire` bucket, and the mirror task
# grades that those two STRINGS come back untouched: that story was re-hosted when it went out,
# and mirror-posts.mjs re-hosts once. Without the bytes the row is still correct and the rundown
# renders a broken image, so rule 2's "what does the page actually show" answer would be wrong
# for a reason that has nothing to do with the task. The bakery cat's card is NOT uploaded here:
# producing it is what the honest mirror run does, and 02-seed.sql deletes it before every
# episode so the guard cannot pass on a previous run's bytes.
python3 -c "import base64,sys,pathlib; sys.stdout.buffer.write(base64.b64decode(pathlib.Path('$HERE/fixture/card.png.b64').read_text()))" > /tmp/popwire-desk-card.png
# The row with no post behind it gets its card too. It is a story that WAS published and whose
# post has since gone, so it carries a re-hosted card like any other; the mirror task's only
# question about it is whether the row is still there afterwards.
for key in cards/marrowgate-stadium-roof-opens-mid-concert.webp \
           cards/marrowgate-stadium-roof-opens-mid-concert.thumb.webp \
           cards/marrowgate-lantern-parade-route-changes-again.webp \
           cards/marrowgate-lantern-parade-route-changes-again.thumb.webp; do
  up=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$API_URL/storage/v1/object/popwire/$key" \
       -H "Authorization: Bearer $SERVICE" -H "content-type: image/png" \
       -H "x-upsert: true" --data-binary @/tmp/popwire-desk-card.png)
  echo "  $key -> $up"
  case "$up" in 200|201) ;; *) echo "the roof story's card could not be uploaded" >&2; exit 1;; esac
done

say "the fixture lane the mirror reads"
# ⛔ THE LANE IS NOT A CONFIGURABLE PATH IN THIS PRODUCT. Agentwire's mirror takes
# AGENTWIRE_LANE; Popwire's does not. scripts/mirror-posts.mjs line 57 reads
#
#     const LANE = path.join(os.homedir(), 'CompoundLabs/compound-ops/social/popwire');
#
# and there is no override anywhere in the file. os.homedir() answers $HOME on POSIX, so the
# only way to point the real script at a fixture lane WITHOUT editing the product is to give
# the run its own HOME. That is what envs/popwire-desk/lanehome is, and prove_graders.py sets
# HOME to it for the mirror run and for nothing else.
#
# ⛔ AND NOTHING HERE HARVESTS ANYTHING. The two files below are pure data. The real lane's
# harvest.mjs, which reads a trending leaderboard, and its agent.mjs, which posts, are never
# run and neither is copied: the mirror imports no lane CODE at all, unlike Agentwire's, which
# imports postedClaims() and keyOf() out of the lane's queue.mjs. So this fixture is entirely
# fabricated and no task here is graded on what any feed carried this morning.
mkdir -p "$LANE"
cp "$HERE/fixture/ledger.jsonl" "$LANE/ledger.jsonl"
cp "$HERE/fixture/reporting.jsonl" "$LANE/reporting.jsonl"
echo "lane ready at $LANE ($(wc -l < "$LANE/ledger.jsonl" | tr -d ' ') ledger row(s), $(wc -l < "$LANE/reporting.jsonl" | tr -d ' ') banked)"

say "app copy"
# ⛔ THE PRODUCT'S OWN .env.local IS EXCLUDED, AND THAT IS THE WHOLE POINT OF RULE 9. It holds
# the PRODUCTION Supabase url and service role key. Copied in, even for the moment before the
# block below overwrites it, that is a production service role key sitting in this tree one
# skipped step away from being the client this app writes through. Same for .vercel,
# .wrangler and .open-next, each of which carries a finished build made against production.
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
NEXT_PUBLIC_SUPABASE_ANON_KEY=$ANON
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
NEXT_PUBLIC_SITE_URL=http://127.0.0.1:$PORT
EOF
[ -d node_modules ] || npm ci --no-audit --no-fund

say "app build"
# ⛔ RULE 9, BOTH HALVES. A build older than its source is the wrong bytes, and a server
# started from it keeps serving them.
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
if [ ! -d .next ] || [ "$CHANGED" -gt 0 ]; then
  # ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). The subscribe task is a click on a
  # React form, and the dev server's hydration is exactly what makes a handler silently not
  # fire.
  #
  # ⛔ AND IT IS THE PRODUCT'S OWN `npm run build`, NEVER `npx next build` (rule 6, second
  # half). Popwire's package.json declares no prebuild today, and that is a fact about this
  # morning rather than a property of the product: the moment one is added, `npx next build`
  # would skip it and this environment would be serving bytes the deploy does not produce.
  #
  # ⛔ AND THE BUILD IS FIREWALLED TOO. Next prerenders /, /search, /feed.xml and the rest
  # through getPosts(), which reads the local stack, and nothing in a build should be able to
  # reach anything else.
  NODE_OPTIONS="--import file://$HERE/harness/no-outbound.mjs" npm run build
fi
desk_stamp_build "$APP" "$API_URL"
echo "built"

say "app"
# A REBUILD WITHOUT A RESTART SERVES THE OLD BUNDLE. `next start` reads .next once, at boot.
#
# ⛔ AND A RESEED WITHOUT A RESTART SERVES THE OLD INDEX. src/lib/wire.ts wraps the table read
# in unstable_cache on a 3600s window (and 86400s for an article), and every page renders
# through it, so a page rendered before 02-seed.sql ran keeps its rows for an hour. The seed
# runs above on every bring-up, so the server is taken down on every bring-up too. This is the
# same class of failure rule 9 describes, with the stale bytes in a cache rather than in .next.
if [ -f /tmp/popwire-desk-app.pid ]; then
  kill "$(cat /tmp/popwire-desk-app.pid)" 2>/dev/null || true
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
  nohup npm start >/tmp/popwire-desk-app.log 2>&1 &
APP_PID=$!
disown "$APP_PID" 2>/dev/null || true
echo "$APP_PID" > /tmp/popwire-desk-app.pid
for _ in $(seq 1 60); do
  curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
  sleep 1
done
echo "started on $PORT (pid $APP_PID, log /tmp/popwire-desk-app.log)"

say "what the pages are actually rendering (rule 2)"
# ⛔ THIS IS MEASURED, NOT ASSUMED, AND IT IS THE CHECK THAT MATTERS MOST ON THIS PRODUCT.
# src/lib/wire.ts reads public.popwire_posts live and FALLS BACK to the committed manifest
# src/data/posts.json when the read fails OR comes back empty:
#
#     if (error || !data || !data.length) return STATIC;
#
# That manifest holds 108 real production entries (measured 2026-09-19). So a broken key, a
# missing table or an RLS surprise does not error: the site renders PRODUCTION's rundown
# against this fixture's database and every headline on screen names a row that does not exist
# here. A page showing stories is not evidence that any row exists.
#
# Marrowgate is a town this environment invented and no production row mentions it, so its
# presence on the page is the proof. The per story page is probed separately because
# getPostForArticle() takes a different path: a direct indexed read by slug, cached per slug,
# added 2026-09-04 after a post published that morning 404'd on its own permalink.
body="$(curl -s -m 20 "http://127.0.0.1:$PORT/")"
echo "$body" | grep -q 'Marrowgate' \
  || { echo "/ does not carry a fixture story: the page is rendering the static fallback, not this database" >&2; exit 1; }
story="$(curl -s -o /dev/null -w '%{http_code}' -m 20 \
         "http://127.0.0.1:$PORT/news/marrowgate-stadium-roof-opens-mid-concert")"
[ "$story" = "200" ] || { echo "the fixture story page answered $story; getPostForArticle is not reading this database" >&2; exit 1; }
# The rundown's subscribe form is the only control on this site that reaches a graded route,
# and it was added on 2026-09-19 to close a hole its own header records: "measured 2026-09-19,
# zero email inputs on the whole app". If it is ever dropped again, the subscribe task stops
# being a browser task, so the bring-up asserts it is there.
echo "$body" | grep -q 'THE RUNDOWN, BY EMAIL' \
  || { echo "/ carries no subscribe form; POST /api/subscribe has no control on any page" >&2; exit 1; }
echo "/ carries the fixture's own stories and the subscribe form, and the story page answers 200"

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app        http://127.0.0.1:$PORT"
echo "  story      http://127.0.0.1:$PORT/news/marrowgate-stadium-roof-opens-mid-concert"
echo "  confirm    http://127.0.0.1:$PORT/api/subscribe/confirm?token=00000000-0000-4000-8000-00000002a701"
echo "  unsub      http://127.0.0.1:$PORT/api/subscribe/unsubscribe?token=00000000-0000-4000-8000-00000002a703"
echo "  prove      uv run python envs/popwire-desk/adversarial/prove_graders.py"
echo "  rollout    node envs/popwire-desk/harness/rollout.mjs"
