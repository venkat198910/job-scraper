#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

LOCAL_NODE_DIR="${JOBTRACK_NODE_DIR:-$HOME/.local/jobtrack-node20}"
if [[ -x "$LOCAL_NODE_DIR/bin/node" && -x "$LOCAL_NODE_DIR/bin/npm" ]]; then
  export PATH="$LOCAL_NODE_DIR/bin:$PATH"
fi

if [[ -n "${FRONTEND_DIR:-}" ]]; then
  WEB_DIR="$(cd "$FRONTEND_DIR" && pwd)"
elif [[ -f "$BACKEND_DIR/../jobs-scraper-web/package.json" ]]; then
  WEB_DIR="$(cd "$BACKEND_DIR/../jobs-scraper-web" && pwd)"
elif [[ -f "$BACKEND_DIR/jobs-scraper-web/package.json" ]]; then
  WEB_DIR="$(cd "$BACKEND_DIR/jobs-scraper-web" && pwd)"
elif [[ -f "$BACKEND_DIR/../jobs-scrapper-web/package.json" ]]; then
  WEB_DIR="$(cd "$BACKEND_DIR/../jobs-scrapper-web" && pwd)"
elif [[ -f "$BACKEND_DIR/jobs-scrapper-web/package.json" ]]; then
  WEB_DIR="$(cd "$BACKEND_DIR/jobs-scrapper-web" && pwd)"
else
  echo "Could not find jobs-scraper-web. Keep it next to job-scraper or set FRONTEND_DIR=/path/to/jobs-scraper-web." >&2
  exit 1
fi

cd "$WEB_DIR"
npm run dev -- --hostname "${JOBTRACK_WEB_HOST:-0.0.0.0}" --port "${PORT:-3000}"
