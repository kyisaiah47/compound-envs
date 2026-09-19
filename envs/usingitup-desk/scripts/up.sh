#!/usr/bin/env bash
# Bring usingitup-desk up from nothing, idempotently.
#
#   ./scripts/up.sh
#
# It applies the schema, the RLS and the fixture, builds an app copy against the LOCAL stack and
# serves it on 3778, creates the storage bucket the pictures go in, and copies the nightly
# publish engine with its credentials pointed at the local stack.
# Safe to re-run: every step either does nothing or does the same thing again.
#
# NEITHER SOURCE TREE IS WRITTEN AND NEITHER IS BUILT IN PLACE (rules 9 and 12).
# `~/CompoundLabs/usingitup` and the ugc engine directory under compound-ops are read and
# rsync'd. `.env*` is excluded from both copies. The product's own `.env.local` names the
# PRODUCTION Supabase project and carries its service role key, and NEXT_PUBLIC_* is inlined at
# BUILD time. Reusing the product's `.next`, or letting its env file come along, serves
# production credentials to the browser and writes live rows.
#
# THE ENGINE IS WHY THAT MATTERS MOST HERE. `publish.mjs` defaults SUPABASE_URL to the PRODUCTION
# project when the variable is unset, and falls back to `~/bin/compound-secret
# SUPABASE_SERVICE_ROLE_KEY` for the key. A shell that forgot one export would upload pictures
# into production storage and upsert and PRUNE the live archive of a site that is up. The copy
# has exactly two lines changed, both of them credential resolution. This script proves that by
# diffing (exactly four changed lines, each naming the thing it replaced) and then by running the
# copy with no environment at all and requiring it to refuse.
#
# NOTHING IN THIS ENVIRONMENT SPENDS A KEY OR SENDS ANYTHING. usingitup reads no model API key
# anywhere in its tree. `grep -rhn "process.env.[A-Z_]*" src/ scripts/ ops/ -o` returns HOME,
# NEXT_PUBLIC_SUPABASE_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and UIU_HOST, and nothing
# else. There is no Stripe code and no mail code. The one thing in the estate that mails this
# publication's list is compound-ops/letters/send-letter.py, and this environment never runs it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${DESK_APP_SRC:-$HOME/CompoundLabs/usingitup}"
UGC_SRC="${DESK_ENGINE_SRC:-$HOME/CompoundLabs/compound-ops/social/ugc}"
APP="$HERE/app"
ENGINE="$HERE/engine"
UGC="$ENGINE/social/ugc"
DB="${DESK_DB_CONTAINER:-supabase_db_stack}"
STACK="${DESK_STACK_DIR:-$HERE/../unemploy-desk/stack}"
PORT="${DESK_APP_PORT:-3778}"

say() { printf '\n== %s\n' "$1"; }

[ -d "$SRC" ] || { echo "product tree not found at $SRC (set DESK_APP_SRC)" >&2; exit 1; }
[ -d "$UGC_SRC" ] || { echo "engine not found at $UGC_SRC (set DESK_ENGINE_SRC)" >&2; exit 1; }

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
  docker cp "$HERE/sql/$f" "$DB:/tmp/usingitup-$f" >/dev/null
  docker exec "$DB" psql -U postgres -d postgres -q -v ON_ERROR_STOP=1 -f "/tmp/usingitup-$f" \
    2>&1 | grep -vE "NOTICE|already exists" || true
  echo "applied $f"
done

# Rule 10. One NULL token column anywhere in the SHARED auth.users makes GoTrue's admin
# list-users answer 500 for EVERY caller on this stack, not just the broken row. usingitup has no
# sign-in and creates no account, so this environment never calls that endpoint. It is repaired
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
# Rule 11: 00000000-0000-4000-8000-0000000fb001 upward is this environment's block in the shared
# auth.users. It is RESERVED AND UNUSED. usingitup has no sign-in, no session and no account
# table, so there is nothing for an auth user to be. Nothing else on this stack may take it.
# The uuids the fixture writes are unsub_tokens, which live in this environment's own table.

say "storage bucket"
# The engine uploads every picture a published entry points at into the public `publication`
# bucket and writes the absolute URL onto the row. Without the bucket every upload answers
# "Bucket not found", the upload helper returns null, and the row falls back to the repo relative
# path, which is a different row from the one production writes.
docker exec "$DB" psql -U postgres -d postgres -q -c "
insert into storage.buckets (id, name, public) values ('publication', 'publication', true)
on conflict (id) do update set public = true;"
echo "bucket publication (public)"

say "app copy"
mkdir -p "$APP"
rsync -a --delete \
  --exclude node_modules --exclude .next --exclude .open-next --exclude .git \
  --exclude .vercel --exclude .wrangler --exclude 'tsconfig.tsbuildinfo' --exclude shots \
  --exclude '.env' --exclude '.env.*' \
  "$SRC"/ "$APP"/
cat > "$APP/.env.local" <<ENVFILE
# Written by envs/usingitup-desk/scripts/up.sh. The product's own .env.local is excluded from the
# rsync: it names the PRODUCTION Supabase project and carries its service role key.
NEXT_PUBLIC_SUPABASE_URL=$API_URL
SUPABASE_URL=$API_URL
# src/lib/live.ts and both /api/subscribe routes read this one. It is the only key the product
# uses anywhere.
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
  nohup npm start >/tmp/usingitup-desk-app.log 2>&1 &
  pid=$!
  disown "$pid" 2>/dev/null || true
  echo "$pid" > /tmp/usingitup-desk-app.pid
  for _ in $(seq 1 90); do
    curl -s -o /dev/null -m 2 "http://127.0.0.1:$PORT/" && break
    sleep 1
  done
  echo "started on $PORT (pid $pid, log /tmp/usingitup-desk-app.log)"
fi

say "publish engine copy"
# publish.mjs resolves the site repo and its tsx binary from its OWN location, with no override:
#
#   DIR      = the file's directory            engine/social/ugc
#   OPS      = resolve(DIR, '../..')           engine
#   PROJECTS = dirname(OPS)                    envs/usingitup-desk
#   TSX      = OPS/node_modules/.bin/tsx       engine/node_modules/.bin/tsx
#   site dir = PROJECTS/usingitup              envs/usingitup-desk/usingitup
#
# The copy is laid out to satisfy that arithmetic rather than patched to change it, and
# `usingitup` is a symlink onto the app copy this script just built. Only the two credential
# lines are touched.
mkdir -p "$UGC"
# `daemon/` is excluded and replaced. The real one is the LIVE posting daemon's working
# directory: it carries the account credentials, an ARMED flag, and a state file whose contents
# change every time a clip goes out. publish.mjs reads one thing out of it, `actioned`, to put the
# permalink and the platform on a row, so the fixture supplies that file and nothing else. A
# fixture that rsync'd the real state would also grade a value that moves on its own.
rsync -a --delete --exclude node_modules --exclude '.env' --exclude '.env.*' \
  --exclude 'reference' --exclude 'sites' --exclude 'capture-pages' --exclude 'reports' \
  --exclude 'path-b-starter' --exclude '.publication-uploads.json' --exclude 'daemon' \
  "$UGC_SRC"/ "$UGC"/
mkdir -p "$UGC/daemon"
cp "$HERE/fixture/state.underconsumption.json" "$UGC/daemon/state.underconsumption.json"
ln -sfn "$APP" "$HERE/usingitup"

python3 - "$UGC_SRC/publish.mjs" "$UGC/publish.mjs" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
before = text
# 1. the production project url the engine falls back to when SUPABASE_URL is unset
text = text.replace("|| 'https://xowekqdsttxwbhfxvusa.supabase.co'", "|| ''")
# 2. the fallback that reads the PRODUCTION service role key out of the vault
text = text.replace("path.join(os.homedir(), 'bin/compound-secret')",
                    "'/nonexistent/no-vault-in-an-environment'")
assert text != before, "neither credential line was found; publish.mjs changed shape"
open(dst, "w", encoding="utf-8").write(text)
PY
changed=$(diff "$UGC_SRC/publish.mjs" "$UGC/publish.mjs" | grep -c '^[<>]' || true)
[ "$changed" = "4" ] || {
  echo "the engine patch changed $changed lines, expected 4 (two lines, in and out)" >&2; exit 1; }
diff "$UGC_SRC/publish.mjs" "$UGC/publish.mjs" | grep '^[<>]' \
  | grep -qvE "supabase\.co|compound-secret|no-vault-in-an-environment" && {
  echo "the engine patch touched a line that is not credential resolution" >&2; exit 1; } || true

[ -f "$ENGINE/package.json" ] || (cd "$ENGINE" && npm init -y >/dev/null 2>&1 || true)
(cd "$ENGINE" && [ -x node_modules/.bin/tsx ] || npm install --silent --no-audit --no-fund tsx@4 @supabase/supabase-js@2)

# Measured, not assumed: run the patched copy with NOTHING in the environment and require it to
# refuse. Unpatched, that same call reaches production. This runs AFTER the install, so a module
# resolution error cannot be mistaken for the refusal.
if (cd "$UGC" && env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY node publish.mjs usingitup \
      >/tmp/usingitup-desk-engine-probe.log 2>&1); then
  echo "the engine ran with no credentials in the environment. Refusing to continue." >&2
  exit 1
fi
grep -q "no SUPABASE_SERVICE_ROLE_KEY" /tmp/usingitup-desk-engine-probe.log || {
  echo "the engine failed for a reason other than the missing key:" >&2
  cat /tmp/usingitup-desk-engine-probe.log >&2; exit 1; }
echo "engine refuses to run without an explicit local key"
cat > "$ENGINE/run.sh" <<RUNNER
#!/usr/bin/env bash
# The nightly publish, scoped to this publication, against the LOCAL stack. This is the same
# entry point sync-site.sh calls at 21:30, with the publication named so the other three sites
# never run.
set -euo pipefail
export SUPABASE_URL="$API_URL"
export SUPABASE_SERVICE_ROLE_KEY="$SERVICE"
exec node "$UGC/publish.mjs" usingitup "\$@"
RUNNER
chmod +x "$ENGINE/run.sh"
echo "engine at $UGC, site symlink $HERE/usingitup points at app"

say "harness"
cd "$HERE/harness"
[ -d node_modules ] || npm install --silent --no-audit --no-fund

say "ready"
echo "  app     http://127.0.0.1:$PORT/"
echo "  publish $ENGINE/run.sh"
echo "  prove   uv run python envs/usingitup-desk/adversarial/prove_graders.py"
echo "  results uv run python tools/validate_results.py usingitup-desk"
