#!/usr/bin/env bash
# Bring the whole environment up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# Stack, schema, RLS, fixture, storage bucket, the fixture's auth users, the app on 3764, and a
# captured session. Safe to re-run: every step either does nothing or does the same thing again.
#
# ⛔ THE APP IS NOT IN THIS REPO. covercheck is a separate tree and the environment builds it from
# there. Publishing this environment to someone who does not have that tree needs the app vendored
# or its image published; see PLAN.md.
#
# ⛔ AND THE ENVIRONMENT IT IS BUILT AND SERVED WITH IS NOT THE ONE IN ITS OWN .env.local. That file
# carries the product's real ANTHROPIC_API_KEY, RESEND_API_KEY and STRIPE_SECRET_KEY, and Next reads
# it on both build and start. Every one of them is overridden below with a non-empty placeholder,
# because Next's env loader replaces a variable that is set to an EMPTY string and leaves a non-empty
# one alone: an empty override would quietly load the real key. What that buys:
#
#   COVERCHECK_EXTRACTION_ENABLED=0   `resolveExtractor()` returns the refusing reader, so no upload
#                                     in this environment can reach a paid model. Proven by the
#                                     extraction row it writes: provider 'not-configured'.
#   ANTHROPIC_API_KEY=<placeholder>   the real key never enters the process at all.
#   RESEND_API_KEY_COMPOUND=""        @compound/mail reads this FIRST and throws
#                                     MailNotConfiguredError on a falsy value, before any network
#                                     call, so no chase and no welcome can leave this machine.
#                                     It is absent from .env.local, so an empty value survives.
#   STRIPE_SECRET_KEY=<placeholder>   /api/checkout is in no task and cannot reach the real account.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/covercheck}"
STACK_DIR="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
PORT="${DESK_APP_PORT:-3764}"
PASSWORD="${DESK_PASSWORD:-covercheck-fixture-password}"
CRON_SECRET="${DESK_CRON_SECRET:-covercheck-desk-local-cron-secret}"

# The desk's own manager, and the QA owner whose organisation IS the demo book. The second one is
# not decoration: `loadConsole()` falls back to `demoOrgId()` when nobody is signed in, that
# function looks for this exact address (src/lib/demo.ts, QA_OWNER_EMAIL), and with no such user
# the whole console fails to render for a visitor. Including the sign-in form, which lives inside
# it. Measured 2026-09-19: the signed-out page read "The coverage book could not be read".
DESK_ID="00000000-0000-4000-8000-0000000000ca"
DESK_EMAIL="${DESK_EMAIL:-desk@harborridgepm.example}"
DEMO_ID="00000000-0000-4000-8000-0000000000cb"
DEMO_EMAIL="qa-covercheck-onboarding-2026-08-18@example.com"

say() { printf '\n== %s\n' "$1"; }

[ -d "$APP_DIR" ] || { echo "app tree not found at $APP_DIR (set DESK_APP_DIR)" >&2; exit 1; }

say "supabase stack"
if ! docker ps --format '{{.Names}}' | grep -qx "$DB"; then
  (cd "$STACK_DIR" && supabase start)
else
  echo "already running"
fi

# Read the keys off the running stack rather than hardcoding them: they are per-project and a
# stale copy here would fail as an auth error somewhere far away from its cause.
say "keys"
STATUS="$(cd "$STACK_DIR" && supabase status -o json)"
key() { echo "$STATUS" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }
API_URL="$(key API_URL)"
PUBLISHABLE="$(key PUBLISHABLE_KEY)"
SERVICE="$(key SERVICE_ROLE_KEY)"
echo "api $API_URL"

say "schema, rls, fixture"
for f in 01-schema.sql 03-rls.sql 02-seed.sql; do
  if [ "$f" = "01-schema.sql" ] && docker exec "$DB" psql -U postgres -d postgres -tAc \
      "select 1 from information_schema.tables where table_name='cc_vendors'" | grep -q 1; then
    echo "skip $f (tables present)"
    continue
  fi
  docker cp "$HERE/sql/$f" "$DB:/tmp/$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/$f" 2>&1 \
    | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

say "fixture auth users"
for pair in "$DESK_ID:$DESK_EMAIL" "$DEMO_ID:$DEMO_EMAIL"; do
  id="${pair%%:*}"; email="${pair#*:}"
  code=$(curl -s -o /tmp/covercheck-desk-user.json -w '%{http_code}' -X POST "$API_URL/auth/v1/admin/users" \
    -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
    -d "{\"id\":\"$id\",\"email\":\"$email\",\"password\":\"$PASSWORD\",\"email_confirm\":true}")
  case "$code" in
    200|201) echo "created $email" ;;
    422)
      # Already there, possibly under a different address if this id was used before. Make the
      # address right, or the demo book will not resolve.
      curl -s -o /dev/null -X PUT "$API_URL/auth/v1/admin/users/$id" \
        -H "apikey: $SERVICE" -H "Authorization: Bearer $SERVICE" -H 'Content-Type: application/json' \
        -d "{\"email\":\"$email\",\"email_confirm\":true}"
      echo "already exists, address confirmed: $email"
      ;;
    *) echo "unexpected $code: $(cat /tmp/covercheck-desk-user.json)" >&2; exit 1 ;;
  esac
done

say "app build"
# Rule 9's other half: a build older than its source is the wrong bytes, and the
# server started from it keeps serving them. See tools/stale-build.sh.
. "$HERE/../../tools/stale-build.sh"
desk_invalidate_stale_build "$APP_DIR" "$API_URL" "$PORT"
cd "$APP_DIR"
export NEXT_PUBLIC_SUPABASE_URL="$API_URL"
export NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY="$PUBLISHABLE"
export SUPABASE_SERVICE_ROLE_KEY="$SERVICE"
export NEXT_PUBLIC_APP_URL="http://127.0.0.1:$PORT"
export COVERCHECK_EXTRACTION_ENABLED=0
export ANTHROPIC_API_KEY=disabled-in-the-eval-environment
export RESEND_API_KEY=disabled-in-the-eval-environment
export RESEND_API_KEY_COMPOUND=
export STRIPE_SECRET_KEY=sk_test_not_used_in_the_eval_environment
export CRON_SECRET="$CRON_SECRET"

# ⛔ `npx next build`, NOT `npm run build`. The package script runs `npm run icons` first, which
# re-vendors Phosphor into src/icons, and a product tree that goes dirty overnight loses its
# nightly deploy. The icons are already vendored in the checkout. .next is gitignored, so building
# leaves the tree exactly as it was: verified with `git status --porcelain` after the first build.
#
# NEXT_PUBLIC_* are baked into the client bundle at BUILD time, so a .next built against the
# production project would point the browser's Supabase client at production while every server
# read went to the local stack. Rebuilt unconditionally for that reason.
npx next build >/tmp/covercheck-desk-build.log 2>&1 || { tail -30 /tmp/covercheck-desk-build.log; exit 1; }
echo "built"

desk_stamp_build "$APP_DIR" "$API_URL"

say "app"
if curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/"; then
  # The build above ran unconditionally, so a server that was already up is serving whatever was
  # in .next before it. Said rather than acted on: killing a port another session is using is not
  # this script's call.
  echo "already serving on $PORT (started before this build; to replace it:"
  echo "  kill \$(cat /tmp/covercheck-desk-app.pid 2>/dev/null || lsof -ti tcp:$PORT) && ./scripts/up.sh)"
else
  # ⛔ DETACHED, AND THAT IS NOT DECORATION. Backgrounded with a plain `&` the server belongs to
  # this script's process group, so whatever called up.sh takes the server down with it when it
  # exits. nohup plus disown detaches it from both.
  nohup npx next start -p "$PORT" >/tmp/covercheck-desk-app.log 2>&1 &
  APP_PID=$!
  disown "$APP_PID" 2>/dev/null || true
  echo "$APP_PID" > /tmp/covercheck-desk-app.pid
  for _ in $(seq 1 40); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $APP_PID, log /tmp/covercheck-desk-app.log)"
fi

say "session"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund
node signin.mjs

say "ready"
echo "  app      http://127.0.0.1:$PORT"
echo "  studio   $(key STUDIO_URL 2>/dev/null || echo 'http://127.0.0.1:54323')"
echo "  prove    uv run python envs/covercheck-desk/adversarial/prove_graders.py"
echo "  rollout  node envs/covercheck-desk/harness/rollout.mjs --task sign-and-approve-the-chase"
echo "  look     node envs/covercheck-desk/harness/look.mjs"
