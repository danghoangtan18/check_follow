#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This build script must be run on macOS."
  exit 1
fi

python3 -m pip install --upgrade pyinstaller

python3 -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "TikTokFollowChecker" \
  --add-data "users.example.txt:." \
  check_follow_gui.py

echo
echo "Build complete:"
echo "  $SCRIPT_DIR/dist/TikTokFollowChecker.app"
