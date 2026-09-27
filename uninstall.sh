#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now yt-limit.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/yt-limit.service" "$HOME/.local/bin/yt-limit"
rm -rf "$HOME/.local/lib/yt-limit"
systemctl --user daemon-reload
echo "Removido. Config e estado ficam em ~/.config/yt-limit e ~/.local/share/yt-limit."
