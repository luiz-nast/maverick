#!/usr/bin/env bash
# Instalação sem root, só para o usuário atual: contador, janela e atalho no menu.
# O bloqueio de sites precisa de root; para ele use packaging/install-system.sh.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB="$HOME/.local/lib/maverick"
BIN="$HOME/.local/bin"
UNITS="$HOME/.config/systemd/user"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
APP_ID=io.github.luiz_nast.Maverick

python3 - <<'PY' || { echo "Faltam dependências: sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-gtk-4.0 gir1.2-adw-1" >&2; exit 1; }
import gi
gi.require_version("Adw", "1")
from gi.repository import Adw
PY

mkdir -p "$LIB" "$BIN" "$UNITS" "$APPS" "$ICONS"
rm -rf "$LIB/maverick" && cp -r "$SRC/maverick" "$LIB/maverick" && rm -rf "$LIB/maverick/__pycache__"

cat > "$BIN/maverick" <<WRAP
#!/bin/sh
exec env PYTHONPATH="$LIB" /usr/bin/python3 -m maverick "\$@"
WRAP
chmod +x "$BIN/maverick"

sed "s|^ExecStart=.*|ExecStart=$BIN/maverick daemon|" "$SRC/data/maverick.service" > "$UNITS/maverick.service"
sed "s|^Exec=.*|Exec=$BIN/maverick|" "$SRC/data/$APP_ID.desktop" > "$APPS/$APP_ID.desktop"
cp "$SRC/data/$APP_ID.svg" "$ICONS/$APP_ID.svg"
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" 2>/dev/null || true

systemctl --user daemon-reload
systemctl --user enable --now maverick.service
echo "Maverick instalado para $USER (sem bloqueio de sites)."
echo "Janela:  maverick    | Status: systemctl --user status maverick"
echo "Bloqueio de sites: packaging/install-system.sh"
