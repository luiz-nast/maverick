#!/usr/bin/env bash
# Remove a instalação de usuário (install.sh). Config e estado são mantidos.
# Para a versão do sistema: sudo apt remove maverick
set -euo pipefail
QUIET=${1:-}
APP_ID=io.github.luiz_nast.Maverick
systemctl --user disable --now maverick.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/maverick.service" "$HOME/.local/bin/maverick" \
      "$HOME/.local/share/applications/$APP_ID.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/$APP_ID.svg"
rm -rf "$HOME/.local/lib/maverick"
# restos do nome antigo
systemctl --user disable --now yt-limit.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/yt-limit.service" "$HOME/.local/bin/yt-limit"
rm -rf "$HOME/.local/lib/yt-limit"
systemctl --user daemon-reload
[ "$QUIET" = "--quiet" ] || echo "Removido. Config e estado ficam em ~/.config/maverick e ~/.local/share/maverick."
