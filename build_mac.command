#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

finish() {
  local exit_code=$?
  echo
  if [[ $exit_code -eq 0 ]]; then
    echo "Build complete."
    echo "App: $SCRIPT_DIR/dist/TikTokFollowChecker.app"
    if [[ -d "$SCRIPT_DIR/dist" ]]; then
      open "$SCRIPT_DIR/dist"
    fi
  else
    echo "Build failed."
  fi
  echo
  read -r -p "Press Enter to close..."
  exit "$exit_code"
}

trap finish EXIT

cd "$SCRIPT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script must be run on macOS."
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found."
  echo "Please install Python 3 first, then run this script again."
  exit 1
fi

chmod +x "$SCRIPT_DIR/build_mac.sh" 2>/dev/null || true
"$SCRIPT_DIR/build_mac.sh"
