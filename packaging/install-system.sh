#!/usr/bin/env bash
# Gera o .deb a partir do repositório, instala com apt e (re)inicia o contador.
set -euo pipefail
DEB=$("$(dirname "${BASH_SOURCE[0]}")/build-deb.sh")
sudo apt install -y "$DEB"
systemctl --user daemon-reload
systemctl --user enable maverick.service
systemctl --user restart maverick.service
echo "Maverick instalado. Abra pelo menu de aplicativos ou rode: maverick"
