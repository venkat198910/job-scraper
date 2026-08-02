#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-3001}"
URL="http://127.0.0.1:${PORT}"
LOG_FILE="${LOG_FILE:-/tmp/jobtrack-web-verify.log}"

cd "$(dirname "${BASH_SOURCE[0]}")/.."

rm -f "$LOG_FILE" /tmp/jobtrack-web-verify.err /tmp/jobtrack-web-verify.html

PORT="$PORT" ./scripts/run-web.sh >"$LOG_FILE" 2>&1 &
pid=$!

cleanup() {
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  if curl -fsS --max-time 2 "$URL" >/tmp/jobtrack-web-verify.html 2>/tmp/jobtrack-web-verify.err; then
    echo "web_start_ok ${URL}"
    exit 0
  fi
  sleep 1
done

echo "web_start_failed ${URL}"
cat "$LOG_FILE" || true
cat /tmp/jobtrack-web-verify.err 2>/dev/null || true
exit 1
