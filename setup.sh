#!/usr/bin/env bash
set -euo pipefail

run_setup() {
  if command -v python3 >/dev/null 2>&1; then
    if python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      exec python3 scripts/local_setup.py "$@"
    fi
    echo "[setup] Existing python3 is older than 3.11."
  fi

  if command -v python >/dev/null 2>&1; then
    if python -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      exec python scripts/local_setup.py "$@"
    fi
    echo "[setup] Existing python is older than 3.11."
  fi
}

install_python() {
  echo "[setup] Python 3 was not found. Trying automatic install..."

  if [[ "$(uname -s)" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      brew install python@3.11 || brew install python
      return
    fi
    echo "Python 3.11+ is missing and Homebrew is not available. Install Python 3.11+ and rerun ./setup.sh" >&2
    exit 1
  fi

  if command -v apt-get >/dev/null 2>&1; then
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      apt-get update
      apt-get install -y python3 python3-venv python3-pip
    elif command -v sudo >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y python3 python3-venv python3-pip
    else
      echo "Python is missing and sudo is not available for apt-get." >&2
      exit 1
    fi
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      dnf install -y python3 python3-pip
    else
      sudo dnf install -y python3 python3-pip
    fi
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      yum install -y python3 python3-pip
    else
      sudo yum install -y python3 python3-pip
    fi
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
      pacman -Sy --noconfirm python python-pip
    else
      sudo pacman -Sy --noconfirm python python-pip
    fi
    return
  fi

  echo "Python 3.11+ is missing and no supported package manager was found." >&2
  exit 1
}

run_setup "$@"
install_python
run_setup "$@"

echo "Python install completed, but python/python3 is not available in this shell yet. Open a new terminal and rerun ./setup.sh" >&2
exit 1
