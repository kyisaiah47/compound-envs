#!/bin/bash
# Sanctioned Cloudflare deployment path for the public Compound Evals console.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

. "$HOME/CompoundLabs/compound-ops/tools/deploy-lock.sh" || { echo "deploy gate missing, refusing to deploy" >&2; exit 1; }
deploy_gate "compound-evals"

echo "==> build"
npx opennextjs-cloudflare build
echo "==> deploy"
npx opennextjs-cloudflare deploy
echo "==> populate incremental cache"
npx opennextjs-cloudflare populateCache remote
echo "==> verify worker routes"
node scripts/verify-cf.mjs "https://compound-evals.kyisaiah47.workers.dev"
