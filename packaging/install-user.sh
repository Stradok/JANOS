#!/usr/bin/env bash
# Install the JANOS app launcher for the current user only (no root). Safe to re-run.
set -euo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$HERE/.." && pwd)
BIN="$HOME/.local/bin"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS="$HOME/.local/share/applications"

mkdir -p "$BIN" "$ICONS" "$APPS"

# Installed copy defaults JANOS_HOME to this repo; an existing JANOS_HOME still wins.
REPO="$REPO" awk 'NR==1 { print; next }
  !done && /^set / { print; print "export JANOS_HOME=\"${JANOS_HOME:-" ENVIRON["REPO"] "}\""; done = 1; next }
  { print }' "$HERE/janos-app" > "$BIN/janos-app.tmp"
chmod 0755 "$BIN/janos-app.tmp"
mv -f "$BIN/janos-app.tmp" "$BIN/janos-app"
echo "installed $BIN/janos-app (JANOS_HOME default: $REPO)"

install -m 0644 "$HERE/janos.svg" "$ICONS/janos.svg"
echo "installed $ICONS/janos.svg"

# Absolute Exec= paths so the launcher runs even when ~/.local/bin is not on the session PATH.
sed "s|^Exec=janos-app|Exec=$BIN/janos-app|" "$HERE/janos.desktop" > "$APPS/janos.desktop"
chmod 0644 "$APPS/janos.desktop"
echo "installed $APPS/janos.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q "$APPS" || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" || true; fi
echo "done. Look for JANOS in the app grid."
