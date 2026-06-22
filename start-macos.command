#!/bin/bash
# ===========================================================
#  Auto Picker - macOS launcher
#  Double-click this file to install (first run) and start.
#  First time: right-click > Open to bypass Gatekeeper, or run
#    chmod +x start-macos.command
# ===========================================================
cd "$(dirname "$0")" || exit 1

# --- Locate Node.js ----------------------------------------
if ! command -v node >/dev/null 2>&1; then
  for p in /usr/local/bin /opt/homebrew/bin; do
    [ -x "$p/node" ] && export PATH="$p:$PATH"
  done
fi

if ! command -v node >/dev/null 2>&1; then
  echo
  echo "  [!] Node.js was not found."
  echo "      Install the LTS version from https://nodejs.org"
  echo "      then double-click this file again."
  echo
  read -r -p "Press Return to close..."
  exit 1
fi

echo
echo "  Auto Picker"
echo "  -----------"
node -v

# --- Install dependencies on first run ---------------------
if [ ! -d "node_modules" ]; then
  echo
  echo "  First run detected - installing dependencies..."
  echo "  (this happens only once and may take a couple of minutes)"
  echo
  npm install || { echo "[!] Dependency install failed."; read -r -p "Press Return..."; exit 1; }
fi

echo
echo "  Starting Auto Picker..."
echo
# Ensure Electron runs as a GUI app, not as plain Node.
unset ELECTRON_RUN_AS_NODE
npm start
