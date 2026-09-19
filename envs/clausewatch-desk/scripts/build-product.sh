#!/usr/bin/env bash
# Bundle the three parts of ClauseWatch this environment runs, straight out of the live tree.
#
#   ./scripts/build-product.sh
#
# ⛔ IT READS THE PRODUCT REPO AND NEVER WRITES TO IT. Everything lands in .build/ here. A dirty
# clausewatch tree at 00:30 costs that product its nightly deploy.
#
# ⛔ AND IT IS A BUNDLE, NOT A COPY. The clause extractor, the nightly predicates and the notice
# drafter are TypeScript inside a Next.js app with a path alias. Re-typing any of them into this
# repository would mean the fixture stops tracking the product the first time a cue regex moves,
# which is the failure the whole environment exists to measure. esbuild resolves `@/` to the
# product's own src and emits ESM that node can import.
#
#   .build/clause-extract.mjs   parseDoc, readContract, evaluate, supports, CLAUSE_KINDS
#   .build/nightly.mjs          worthRaising, signalTitle (the raise predicate and its wording)
#   .build/notices.mjs          draftNonRenewal (the letter the product composes)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${DESK_APP_DIR:-$HOME/CompoundLabs/clausewatch}"
ESBUILD="$APP_DIR/node_modules/.bin/esbuild"

[ -d "$APP_DIR" ] || { echo "clausewatch tree not found at $APP_DIR (set DESK_APP_DIR)" >&2; exit 1; }
[ -x "$ESBUILD" ] || { echo "esbuild not found at $ESBUILD (run npm install in $APP_DIR)" >&2; exit 1; }

mkdir -p "$HERE/.build"

bundle() {
  "$ESBUILD" "$APP_DIR/$1" --bundle --format=esm --platform=node \
    --alias:@="$APP_DIR/src" --outfile="$HERE/.build/$2" --log-level=error
  echo "  $2  <- $1"
}

echo "bundling from $APP_DIR"
bundle "src/product/clause-extract/index.ts"      "clause-extract.mjs"
bundle "src/app/_lib/clausewatch/nightly.ts"      "nightly.mjs"
bundle "src/app/_lib/clausewatch/notices.ts"      "notices.mjs"

# Proof the bundles export what the seed generator imports. A silent rename upstream would
# otherwise surface as a seed full of `undefined` rather than as an error here.
node --input-type=module -e "
const c = await import('$HERE/.build/clause-extract.mjs');
const n = await import('$HERE/.build/nightly.mjs');
const s = await import('$HERE/.build/notices.mjs');
const want = { 'clause-extract': ['parseDoc','readContract','evaluate','supports','CLAUSE_KINDS'],
               nightly: ['worthRaising','signalTitle'], notices: ['draftNonRenewal'] };
const got = { 'clause-extract': c, nightly: n, notices: s };
const bad = [];
for (const [m, keys] of Object.entries(want))
  for (const k of keys) if (typeof got[m][k] === 'undefined') bad.push(m + '.' + k);
if (bad.length) { console.error('missing exports: ' + bad.join(', ')); process.exit(1); }
console.log('  exports ok');
"
