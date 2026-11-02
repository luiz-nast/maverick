#!/usr/bin/env bash
# Gera o .deb a partir do repositório, instala com apt e (re)inicia o contador.
set -euo pipefail
DEB=$("$(dirname "${BASH_SOURCE[0]}")/build-deb.sh")
sudo apt install -y "$DEB"
systemctl --user daemon-reload
systemctl --user enable maverick.service
systemctl --user restart maverick.service
# Extensão do GNOME que diz qual janela está em foco; carrega no próximo login.
EXT=maverick@luiz-nast.github.io
EXTS=$(gsettings get org.gnome.shell enabled-extensions)
if [[ "$EXTS" != *"$EXT"* ]]; then
    gsettings set org.gnome.shell enabled-extensions \
        "$(python3 -c "import ast,sys; print(ast.literal_eval(sys.argv[1].replace('@as ', '')) + [sys.argv[2]])" "$EXTS" "$EXT")"
    echo "Extensão do foco ligada: saia e entre de novo na sessão para ela carregar."
fi
echo "Maverick instalado. Abra pelo menu de aplicativos ou rode: maverick"
