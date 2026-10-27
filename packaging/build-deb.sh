#!/usr/bin/env bash
# Build dist/janos_0.1.0_all.deb from packaging/ in a temp staging dir. Needs no root.
set -euo pipefail

VERSION=0.1.0
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
OUT="$HERE/../dist"
DEB="$OUT/janos_${VERSION}_all.deb"

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

install -d "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" "$STAGE/usr/share/doc/janos" \
  "$STAGE/etc/janos" "$STAGE/DEBIAN"

install -m 0755 "$HERE/janos-app" "$STAGE/usr/bin/janos-app"
install -m 0644 "$HERE/janos.desktop" "$STAGE/usr/share/applications/janos.desktop"
install -m 0644 "$HERE/janos.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/janos.svg"

cat > "$STAGE/usr/share/doc/janos/README" <<'README'
JANOS desktop launcher

Starts the local JANOS server (if it is not already running) in full-access
mode and opens the HUD in its own app window. The server itself is not
packaged: this launcher runs the JANOS repo's jarvis-core/.venv.

Where the repo is: JANOS_HOME, taken from the environment first, then from
/etc/janos/janos.conf, then $HOME/Desktop/JANOS. Edit /etc/janos/janos.conf
to point it elsewhere.

For the best window, install Chromium (for example: sudo snap install chromium).
Without a Chromium-based browser the launcher opens the HUD in your default browser.

Stop the server from the app grid action "Quit JANOS", or run: janos-app --stop
README
chmod 0644 "$STAGE/usr/share/doc/janos/README"

cat > "$STAGE/etc/janos/janos.conf" <<'CONF'
# JANOS_HOME=/home/you/Desktop/JANOS
CONF
chmod 0644 "$STAGE/etc/janos/janos.conf"
echo /etc/janos/janos.conf > "$STAGE/DEBIAN/conffiles"

cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: janos
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Maintainer: JANOS owner <noreply@localhost>
Depends: curl
Recommends: chromium | google-chrome-stable
Description: JANOS desktop launcher
 Starts the local JANOS assistant server and opens its HUD in an app window.
 Needs the JANOS repo (see /etc/janos/janos.conf).
CONTROL

# Refresh desktop and icon caches after install and removal; never fail the package step.
cat > "$STAGE/DEBIAN/postinst" <<'HOOK'
#!/bin/sh
if command -v update-desktop-database >/dev/null 2>&1; then update-desktop-database -q /usr/share/applications || true; fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi
exit 0
HOOK
cp "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
chmod 0755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

mkdir -p "$OUT"
dpkg-deb --root-owner-group --build "$STAGE" "$DEB"
echo "Built $DEB"
