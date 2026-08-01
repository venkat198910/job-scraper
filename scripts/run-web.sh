#!/usr/bin/env bash
set -euo pipefail

BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
npm run dev -- --hostname 0.0.0.0 --port 3000
