#!/usr/bin/env bash
# Instala o Maverick como aplicativo do sistema: gera o .deb, remove a instalação
# de usuário (se houver), instala com apt e inicia o contador nesta sessão.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEB=$("$ROOT/packaging/build-deb.sh")
"$ROOT/uninstall.sh" --quiet || true
sudo apt install -y "$DEB"
systemctl --user daemon-reload
systemctl --user enable --now maverick.service
echo
echo "Maverick instalado. Abra pelo menu de aplicativos ou rode: maverick"
