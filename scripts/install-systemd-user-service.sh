#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-jobtrack-web}"
PORT="${PORT:-3000}"
NODE_VERSION="${NODE_VERSION:-v20.19.4}"
LOCAL_NODE_DIR="${JOBTRACK_NODE_DIR:-$HOME/.local/jobtrack-node20}"
if [[ -x "$LOCAL_NODE_DIR/bin/node" && -x "$LOCAL_NODE_DIR/bin/npm" ]]; then
  export PATH="$LOCAL_NODE_DIR/bin:$PATH"
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl was not found. This installer must run inside Linux/WSL with systemd enabled." >&2
  exit 1
fi

if ! systemctl --user status >/dev/null 2>&1; then
  echo "systemd user services are not available in this shell." >&2
  echo "If this is WSL, enable systemd in /etc/wsl.conf, restart WSL, then rerun this script." >&2
  exit 1
fi

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
  echo "Could not find jobs-scraper-web next to backend." >&2
  echo "Set FRONTEND_DIR=/path/to/jobs-scraper-web and rerun." >&2
  exit 1
fi

if [[ ! -f "$WEB_DIR/package.json" ]]; then
  echo "Frontend package.json not found: $WEB_DIR" >&2
  exit 1
fi

node_major() {
  local version
  version="$(node --version 2>/dev/null || true)"
  version="${version#v}"
  version="${version%%.*}"
  [[ "$version" =~ ^[0-9]+$ ]] && echo "$version" || echo "0"
}

install_node20() {
  echo "Node.js/npm missing or too old. Installing user-local Node.js $NODE_VERSION ..."

  local machine arch archive url tmpdir
  machine="$(uname -m)"
  case "$machine" in
    x86_64|amd64) arch="x64" ;;
    aarch64|arm64) arch="arm64" ;;
    *)
      echo "Unsupported Linux architecture for automatic Node install: $machine" >&2
      exit 1
      ;;
  esac

  if command -v curl >/dev/null 2>&1 && command -v tar >/dev/null 2>&1; then
    tmpdir="$(mktemp -d)"
    archive="$tmpdir/node.tar.xz"
    url="https://nodejs.org/dist/$NODE_VERSION/node-$NODE_VERSION-linux-$arch.tar.xz"
    curl -fsSL "$url" -o "$archive"
    rm -rf "$LOCAL_NODE_DIR"
    mkdir -p "$LOCAL_NODE_DIR"
    tar -xJf "$archive" -C "$LOCAL_NODE_DIR" --strip-components=1
    rm -rf "$tmpdir"
    export PATH="$LOCAL_NODE_DIR/bin:$PATH"
    return
  fi

  echo "curl/tar not available for user-local Node install. Falling back to system package manager..."
  if command -v apt-get >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
      apt-get update
      apt-get install -y ca-certificates curl gnupg
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
      apt-get install -y nodejs
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y ca-certificates curl gnupg
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
      sudo apt-get install -y nodejs
    else
      echo "sudo is required to install Node.js 20 with apt-get." >&2
      exit 1
    fi
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
      dnf install -y nodejs npm
    else
      sudo dnf install -y nodejs npm
    fi
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
      yum install -y nodejs npm
    else
      sudo yum install -y nodejs npm
    fi
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    if [[ "$(id -u)" -eq 0 ]]; then
      pacman -Sy --noconfirm nodejs npm
    else
      sudo pacman -Sy --noconfirm nodejs npm
    fi
    return
  fi

  echo "No supported package manager found for installing Node.js 20." >&2
  exit 1
}

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1 || [[ "$(node_major)" -lt 20 ]]; then
  install_node20
fi

NPM_BIN="$(command -v npm || true)"
NODE_BIN="$(command -v node || true)"
if [[ -z "$NPM_BIN" || -z "$NODE_BIN" || "$(node_major)" -lt 20 ]]; then
  echo "Node.js 20+/npm is still unavailable after install attempt." >&2
  exit 1
fi

PYTHON_BIN="$BACKEND_DIR/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON3_BIN="$(command -v python3 || command -v python || true)"
  if [[ -z "$PYTHON3_BIN" ]]; then
    echo "Python was not found inside Linux/WSL. Run ./setup.sh first, then rerun this installer." >&2
    exit 1
  fi
  echo "Linux backend venv not found. Creating $BACKEND_DIR/.venv ..."
  "$PYTHON3_BIN" -m venv "$BACKEND_DIR/.venv"
  "$PYTHON_BIN" -m pip install --upgrade pip
  "$PYTHON_BIN" -m pip install -r "$BACKEND_DIR/requirements.txt"
  "$PYTHON_BIN" -m playwright install chromium || true
fi

if [[ ! -d "$WEB_DIR/node_modules" ]]; then
  echo "Frontend node_modules not found. Installing npm dependencies ..."
  if [[ -f "$WEB_DIR/package-lock.json" ]]; then
    (cd "$WEB_DIR" && "$NPM_BIN" ci)
  else
    (cd "$WEB_DIR" && "$NPM_BIN" install)
  fi
fi

SERVICE_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$SERVICE_DIR"
SERVICE_FILE="$SERVICE_DIR/${SERVICE_NAME}.service"

cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=JobTrack Web UI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$WEB_DIR
Environment=NODE_ENV=development
Environment=PATH=$(dirname "$NODE_BIN"):/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
Environment=APPLICATION_ASSISTANT_DIR=$BACKEND_DIR
Environment=APPLICATION_ASSISTANT_PYTHON=$PYTHON_BIN
ExecStart=$NPM_BIN run dev -- --hostname 0.0.0.0 --port $PORT
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "${SERVICE_NAME}.service"

echo "Installed and started ${SERVICE_NAME}.service"
echo
echo "Status:"
echo "  systemctl --user status ${SERVICE_NAME}.service"
echo
echo "Logs:"
echo "  journalctl --user -u ${SERVICE_NAME}.service -f"
echo
echo "Stop:"
echo "  systemctl --user stop ${SERVICE_NAME}.service"
echo
echo "The web UI should listen on http://localhost:${PORT}"
