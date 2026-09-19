# desk_invalidate_stale_build <app-dir> <api-url> <port>
#
# Rule 9's other half, and the half that actually bit. Rule 9 says never reuse the PRODUCT'S
# .next, because NEXT_PUBLIC_* is inlined at build time. What it did not say is that an
# environment's OWN .next goes stale the same way, and every up.sh in this repo had some version
# of `[ -d .next ] || npm run build`. So after a source change the script printed "built" and
# "already serving on <port>" and served the bytes from before the change.
#
# Measured 2026-09-19 on parserail-desk. A live SSRF was fixed in the product, up.sh was re-run,
# and the probe still handed the caller's API key to the attacker's listener, because
# .next/BUILD_ID was 15:04:08 and the fixed route.ts was 15:25:41. The fix was correct and the
# thing under test was the old build. That is a grader measuring code nobody is running, which is
# the one failure this whole repo exists to prevent.
#
# This runs BEFORE each script's own build step and simply removes a build that cannot be current,
# so whatever logic that script already has (an unconditional build, an API stamp, or the `[ -d
# .next ]` test) does the right thing afterwards. It also frees the port when it invalidates,
# because a server started from the old build keeps serving it no matter what gets built next.
desk_invalidate_stale_build() {
  local app="$1" api="$2" port="$3"
  local stamp="$app/.next/.desk-api-stamp"
  local reason=""

  [ -d "$app/.next" ] || return 0

  if [ ! -f "$app/.next/BUILD_ID" ]; then
    reason="the last build did not finish"
  elif [ "$(cat "$stamp" 2>/dev/null)" != "$api" ]; then
    reason="the existing build was made for a different Supabase API"
  else
    # Any tracked input newer than the build. `find -newer` compares mtime, and the rsync that
    # copies the product in preserves mtimes, so a change in the product tree shows up here too.
    local newer
    newer="$(cd "$app" 2>/dev/null && find src app public package.json package-lock.json \
             next.config.js next.config.mjs next.config.ts tsconfig.json \
             -newer .next/BUILD_ID 2>/dev/null | head -1)"
    [ -n "$newer" ] && reason="a source file changed since the last build ($newer)"
  fi

  [ -n "$reason" ] || return 0

  echo "discarding the existing build: $reason"
  rm -rf "$app/.next"

  local pids
  pids="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    echo "stopping the server on $port: it is serving the build just discarded"
    for pid in $pids; do kill "$pid" 2>/dev/null || true; done
    sleep 2
  fi
}

# Record which API the build that just finished was made against. Call after the build step.
desk_stamp_build() {
  local app="$1" api="$2"
  [ -d "$app/.next" ] && printf '%s' "$api" > "$app/.next/.desk-api-stamp"
}
