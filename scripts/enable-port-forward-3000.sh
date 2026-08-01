#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-3000}"

echo "For macOS/Linux, the web UI normally only needs to listen on 0.0.0.0:"
echo "  ./scripts/run-web.sh"
echo
echo "If your firewall blocks port ${PORT}, open it with your OS firewall tool."
echo
echo "Ubuntu ufw:"
echo "  sudo ufw allow ${PORT}/tcp"
echo
echo "firewalld:"
echo "  sudo firewall-cmd --add-port=${PORT}/tcp --permanent"
echo "  sudo firewall-cmd --reload"
