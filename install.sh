#!/usr/bin/env bash
# Instala o yt-limit como serviço systemd de usuário (inicia junto com a sessão).
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="$HOME/.local/lib/yt-limit"
UNIT_DIR="$HOME/.config/systemd/user"
BIN_DIR="$HOME/.local/bin"

python3 -c 'import gi; gi.require_version("Gtk","3.0"); from gi.repository import Gtk' 2>/dev/null || {
  echo "Falta o PyGObject/GTK3. No Ubuntu: sudo apt install python3-gi gir1.2-gtk-3.0" >&2
  exit 1
}

mkdir -p "$LIB_DIR" "$UNIT_DIR" "$BIN_DIR"
rm -rf "$LIB_DIR/yt_limit"
cp -r "$SRC_DIR/yt_limit" "$LIB_DIR/yt_limit"

cat > "$BIN_DIR/yt-limit" <<WRAP
#!/usr/bin/env bash
exec env PYTHONPATH="$LIB_DIR" python3 -m yt_limit "\$@"
WRAP
chmod +x "$BIN_DIR/yt-limit"

cat > "$UNIT_DIR/yt-limit.service" <<UNIT
[Unit]
Description=yt-limit: limite diário de YouTube
After=graphical-session.target
PartOf=graphical-session.target

[Service]
Type=simple
Environment=PYTHONPATH=$LIB_DIR
Environment=GDK_BACKEND=x11
ExecStart=/usr/bin/python3 -m yt_limit
Restart=on-failure
RestartSec=3

[Install]
WantedBy=graphical-session.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now yt-limit.service
echo "Instalado. Status: systemctl --user status yt-limit"
echo "Logs:             journalctl --user -u yt-limit -f"
echo "CLI:              yt-limit --status | --limit 30 | --reset"
