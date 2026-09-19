#!/usr/bin/env bash
# Bring wirecall-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Schema, RLS, fixture, an app copy built against the LOCAL stack with the LOCAL fixture frozen
# into it, and the app on 3374. Safe to re-run: every step either does nothing or does the same
# thing again.
#
# ⛔ THE SUPABASE STACK IS SHARED AND ALREADY RUNNING. This script never starts one, never
# creates a second one and never changes a port. It reads the keys off whatever is serving at
# 127.0.0.1:54321 and adds WireCall's tables to it.
#
# ⛔ THE APP IS BUILT IN envs/wirecall-desk/app, NEVER IN ~/CompoundLabs/wirecall (rules 9 and
# 12). NEXT_PUBLIC_* is inlined at BUILD time, so reusing the product's own .next would serve the
# PRODUCTION Supabase url and publishable key to the browser and this environment would quietly
# be driving the live project. Building a copy also keeps the product tree clean, which is what
# the 00:30 deploy sweep requires.
#
# ⛔ NO PAID KEY IS EVER SET, AND THE APP CANNOT REACH ONE.
#   * STRIPE_SECRET_KEY below is a fixture string. WireCall uses that variable as the HMAC
#     secret for the device key (src/lib/device.ts) and the opt-in token (src/lib/optin.ts), so
#     four of the seven routes need it set and none of those four reaches Stripe.
#     WIRECALL IS ON THE SECOND LIVE STRIPE ACCOUNT ON THIS MACHINE, the one OutRip and MatchLine
#     carry. The real key is never read here and /api/checkout is not graded.
#   * STRIPE_WEBHOOK_SECRET is likewise only an HMAC key. `constructEvent` verifies bytes and
#     makes no network call, which is what lets the Wire Pass task run end to end offline.
#   * RESEND_API_KEY is deliberately ABSENT, so the house sender throws MailNotConfiguredError
#     and nothing is sent.
#   * AND THE SERVER RUNS BEHIND harness/no-outbound.mjs, preloaded with NODE_OPTIONS, which
#     refuses every fetch that is not the local stack. That is the layer that stops the remote
#     template render inside the mailer, which happens BEFORE the missing-key check.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SRC="${DESK_APP_DIR:-$HOME/CompoundLabs/wirecall}"
APP="$HERE/app"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3374}"
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
# ⛔ 02-seed.sql NEVER TRUNCATES frontwire_posts OR popwire_posts. frontwire-desk owns
# frontwire_posts on this stack and truncates it in its own seed; this fixture only ever touches
# rows whose slug begins `wcdesk-`, so the two environments coexist in either order.
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  docker cp "$HERE/sql/$f" "$DB:/tmp/wirecall-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/wirecall-$f" 2>&1 \
    | grep -vE "NOTICE|already exists|setval|^-+$|^\s*$|^\(1 row\)$" || true
  echo "applied $f"
done

# ⛔ RULE 10. One NULL token column anywhere in the SHARED auth.users 500s admin list-users for
# every environment on this stack, and a product reads that 500 as "there is no demo account".
# WireCall has no accounts at all and never calls GoTrue, so it cannot cause this and cannot be
# hurt by it. The repair still runs, because this environment shares the table with the ones
# that do, and leaving a neighbour broken is the same as breaking it.
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

say "the public read, as the browser makes it"
# The board has to answer and the address column has to stay shut. Both are measured rather than
# assumed, because scripts/capture.mjs below reads exactly these and 01-schema.sql deliberately
# creates wc_leaderboard without the security_invoker option production declares. sql/03-rls.sql
# carries the measurement that decided that.
board=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/wc_leaderboard?select=rank" \
        -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
mail=$(curl -s -o /dev/null -w '%{http_code}' "$API_URL/rest/v1/wc_players?select=email&limit=1" \
       -H "apikey: $PUBLISHABLE" -H "Authorization: Bearer $PUBLISHABLE")
echo "wc_leaderboard -> $board (200 expected), wc_players?select=email -> $mail (401 expected)"
[ "$board" = "200" ] || { echo "the public board does not read; the capture below would fail" >&2; exit 1; }
[ "$mail" = "200" ] && { echo "the publishable key can read player addresses; refusing to continue" >&2; exit 1; }

say "app copy"
# ⛔ THE PRODUCT'S OWN .env.local IS EXCLUDED, AND THAT IS THE WHOLE POINT OF RULE 9. It carries
# the PRODUCTION Supabase url and publishable key, and the live Stripe secret for the second
# account. Copied in, even for the moment before the block below overwrites it, it is a
# production credential sitting in this tree and one skipped step away from being built into a
# browser bundle. Same for .vercel, which holds .env.production.local.
#
# ⛔ AND data/wirecall/*.json IS EXCLUDED FOR THE SAME REASON. Those four files are a frozen read
# of the PRODUCTION database, and they are what every page on this site renders. Copied in, the
# console would be showing production's slate until the capture step below overwrote them. The
# capture owns that directory outright here; scripts/capture.mjs creates it if it is missing.
CHANGED="$(rsync -a --delete --itemize-changes \
      --exclude node_modules --exclude .next --exclude .open-next \
      --exclude .git --exclude .vercel --exclude .wrangler \
      --exclude '.env*' --exclude tsconfig.tsbuildinfo \
      --exclude 'data/wirecall/*.json' \
      "$APP_SRC"/ "$APP"/ | grep -vcE '^$|^\.d\.\.t\.+ \./$' || true)"
# The bare `./` line rsync always prints for the destination directory's own mtime is dropped:
# left in, CHANGED is never 0 and every bring-up rebuilds whether or not anything moved.
echo "copied to $APP ($CHANGED paths changed)"

cd "$APP"
cat > .env.local <<EOF
NEXT_PUBLIC_SUPABASE_URL=$API_URL
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=$PUBLISHABLE
SUPABASE_SERVICE_ROLE_KEY=$SERVICE
NEXT_PUBLIC_SITE_URL=http://127.0.0.1:$PORT
STRIPE_SECRET_KEY=wirecall-desk-fixture-hmac-secret-not-a-stripe-key
STRIPE_WEBHOOK_SECRET=whsec_wirecall_desk_fixture
EOF
[ -d node_modules ] || npm ci --no-audit --no-fund

say "freeze the fixture into the pages (the product's own capture)"
# ⛔ RULE 2, AND THIS IS THE STEP THAT MAKES A BROWSER TASK POSSIBLE AT ALL. WireCall renders
# every page out of data/wirecall/*.json, which scripts/capture.mjs freezes off the public read.
# The copy ships with PRODUCTION's capture, so without this step the console would render
# production's slate, the story ids on screen would name rows that do not exist locally, and a
# click would answer "That story is not on a live slate."
#
# This runs the product's OWN capture script, unmodified, pointed at the local stack. Nothing
# here writes a data file by hand.
NEXT_PUBLIC_SUPABASE_URL="$API_URL" NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="$PUBLISHABLE" \
  node scripts/capture.mjs

# The capture lands in data/, which the shared stale-build guard does not walk (it checks src,
# app, public and the config files). So the capture gets its own stamp, or a rebuilt fixture
# would be served from a bundle that still has the old slate inlined.
# The hash is over the ROWS, not the files, because capture.mjs stamps a fresh `captured_at` on
# every run.
#
# ⛔ IT STILL CHANGES ON EVERY BRING-UP, AND THAT IS CORRECT RATHER THAN A MISS. The fixture's
# clock is relative: 02-seed.sql writes opens_at, locks_at and settled_at from now() so the open
# slate is always open, and the seed runs above this. So the captured slate times move every
# time, the build is discarded, and the console's own lock countdown is rebuilt fresh. A page
# carrying an older run's lock time is exactly the stale-bytes failure rule 9 is about: the
# console disables every control the moment that time passes.
CAP="$(python3 -c '
import glob, hashlib, json
h = hashlib.sha256()
for p in sorted(glob.glob("data/wirecall/*.json")):
    d = json.load(open(p))
    d.pop("captured_at", None)
    h.update(p.encode()); h.update(json.dumps(d, sort_keys=True).encode())
print(h.hexdigest())')"
if [ -d .next ] && [ "$(cat .next/.desk-capture-stamp 2>/dev/null)" != "$CAP" ]; then
  echo "discarding the existing build: it has a different capture inlined"
  rm -rf .next
  pids="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null || true)"
  for pid in $pids; do kill "$pid" 2>/dev/null || true; done
  [ -n "$pids" ] && sleep 2
fi

say "app build"
# ⛔ RULE 9, BOTH HALVES. A build older than its source is the wrong bytes, and a server started
# from it keeps serving them.
desk_invalidate_stale_build "$APP" "$API_URL" "$PORT"
REBUILT=0
if [ ! -d .next ] || [ "$CHANGED" -gt 0 ]; then
  # ⛔ A PRODUCTION BUILD, NEVER THE DEV SERVER (rule 6). The dev server's hydration is the thing
  # that makes a React handler silently not fire, and the one browser task here is a click.
  npm run build
  REBUILT=1
fi
desk_stamp_build "$APP" "$API_URL"
printf '%s' "$CAP" > .next/.desk-capture-stamp
echo "built"

say "app"
# A REBUILD WITHOUT A RESTART SERVES THE OLD BUNDLE. `next start` reads .next once, at boot.
if [ "$REBUILT" = 1 ] && [ -f /tmp/wirecall-desk-app.pid ]; then
  kill "$(cat /tmp/wirecall-desk-app.pid)" 2>/dev/null || true
  sleep 2
fi
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  echo "already serving on $PORT"
else
  # ⛔ DETACHED. Backgrounded with a plain `&` the server belongs to this script's process group,
  # so whatever called up.sh takes the server down with it when it exits.
  # ⛔ AND BEHIND THE OUTBOUND FIREWALL. See the header: the mailer renders remotely before it
  # checks for a key, so "no key" alone does not keep this environment offline.
  NODE_OPTIONS="--import file://$HERE/harness/no-outbound.mjs" \
    nohup npm start >/tmp/wirecall-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/wirecall-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/wirecall-desk-app.log)"
fi

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app     http://127.0.0.1:$PORT"
echo "  slate   http://127.0.0.1:$PORT/"
echo "  device  http://127.0.0.1:$PORT/history"
echo "  prove   uv run python envs/wirecall-desk/adversarial/prove_graders.py"
