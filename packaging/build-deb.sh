#!/usr/bin/env bash
# Gera dist/maverick_<versão>_all.deb a partir do código do repositório.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/maverick/__init__.py")
PKG="maverick_${VERSION}_all"
STAGE="$ROOT/build/$PKG"
rm -rf "$STAGE" && mkdir -p "$STAGE/DEBIAN" "$ROOT/dist"

inst() { install -D -m "$1" "$2" "$STAGE/$3"; }

for f in "$ROOT"/maverick/*.py; do inst 644 "$f" "usr/lib/maverick/maverick/$(basename "$f")"; done
inst 755 "$ROOT/data/maverick-blockctl" usr/lib/maverick/maverick-blockctl
inst 644 "$ROOT/data/maverick.service" usr/lib/systemd/user/maverick.service
inst 644 "$ROOT/data/io.github.luiz_nast.Maverick.desktop" usr/share/applications/io.github.luiz_nast.Maverick.desktop
inst 644 "$ROOT/data/io.github.luiz_nast.Maverick.svg" usr/share/icons/hicolor/scalable/apps/io.github.luiz_nast.Maverick.svg
inst 644 "$ROOT/data/io.github.luiz_nast.Maverick.policy" usr/share/polkit-1/actions/io.github.luiz_nast.Maverick.policy
inst 644 "$ROOT/LICENSE" usr/share/doc/maverick/copyright

mkdir -p "$STAGE/usr/bin"
cat > "$STAGE/usr/bin/maverick" <<'WRAP'
#!/bin/sh
exec env PYTHONPATH=/usr/lib/maverick /usr/bin/python3 -m maverick "$@"
WRAP
chmod 755 "$STAGE/usr/bin/maverick"

SIZE=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CTRL
Package: maverick
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Installed-Size: $SIZE
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), libnotify-bin, pkexec | policykit-1
Maintainer: Luiz Felipe Nast <luizfelipenast@gmail.com>
Homepage: https://github.com/luiz-nast/maverick
Description: Limite diário de YouTube e bloqueio de sites de jogos
 Conta só o tempo em que um vídeo do YouTube está de fato tocando (MPRIS),
 mostra um contador na tela, pausa o vídeo ao atingir o limite diário e
 bloqueia sites de jogos de navegador via /etc/hosts e políticas do
 Firefox e do Chrome.
CTRL

cat > "$STAGE/DEBIAN/postinst" <<'SH'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    /usr/lib/maverick/maverick-blockctl reapply-or-defaults || echo "maverick: falha ao aplicar o bloqueio de sites" >&2
    systemctl --global enable maverick.service >/dev/null 2>&1 || true
    if command -v gtk-update-icon-cache >/dev/null; then gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true; fi
    if command -v update-desktop-database >/dev/null; then update-desktop-database -q /usr/share/applications || true; fi
fi
exit 0
SH

cat > "$STAGE/DEBIAN/prerm" <<'SH'
#!/bin/sh
set -e
if [ "$1" = "remove" ]; then
    /usr/lib/maverick/maverick-blockctl clear || true
    systemctl --global disable maverick.service >/dev/null 2>&1 || true
fi
exit 0
SH
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/prerm"

dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$ROOT/dist/$PKG.deb" >/dev/null
echo "$ROOT/dist/$PKG.deb"
