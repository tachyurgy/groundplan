#!/usr/bin/env bash
# Build and deploy one stack's front end to Cloudflare Pages.
#   scripts/deploy-pages.sh python|go
# Needs CLOUDFLARE_API_TOKEN + CLOUDFLARE_ACCOUNT_ID. API_ORIGIN is a Pages project secret, set once:
#   printf %s https://gp-python-api.levelbrook.com | wrangler pages secret put API_ORIGIN --project-name gp-python
set -euo pipefail
stack="${1:?python|go}"
project="gp-${stack}"
here="$(cd "$(dirname "$0")/.." && pwd)"
stage="${STAGE_DIR:-${TMPDIR:-/tmp}/gp-deploy-${stack}}"
rm -rf "$stage" && mkdir -p "$stage/functions/api"

cd "$here"
VITE_STACK="$stack" npx vite build --outDir "$stage/dist" --emptyOutDir >/dev/null
node scripts/check-bundle.mjs "$stage/dist"
cp "functions/api/[[path]].ts" "$stage/functions/api/"

# lbtrack page-view tracker: /lb.js + the /e collector Function, next to our /api proxy.
python3 "$HOME/Desktop/levelbrook/lbtrack/install.py" "$stage/dist" >/dev/null
mv "$stage/dist/functions/e.js" "$stage/functions/e.js" && rmdir "$stage/dist/functions"

# Only these paths run Functions; everything else is served as a static asset (SPA fallback to index.html).
cat > "$stage/dist/_routes.json" <<'JSON'
{ "version": 1, "include": ["/api/*", "/e"], "exclude": [] }
JSON
cat > "$stage/dist/_headers" <<'HDR'
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
HDR

cd "$stage"
npx wrangler pages deploy dist --project-name="$project" --branch=main --commit-dirty=true
