# yt-limit

Limite diário de YouTube para Linux, como aplicativo de sistema (sem extensão de navegador).

Conta **só o tempo em que um vídeo está de fato tocando**. Aba aberta, vídeo pausado ou
aba em segundo plano sem reprodução não gastam o seu tempo. Ao atingir o limite (30 min por
padrão), o app pausa o vídeo via D-Bus e mostra uma tela de aviso; qualquer tentativa de dar
play de novo é pausada no segundo seguinte. O contador zera à meia-noite.

## Como funciona

Firefox e Chrome/Chromium publicam a mídia da página como um player **MPRIS** no D-Bus da
sessão, com `PlaybackStatus` (Playing/Paused) e metadados (URL da página no Firefox, capa
do vídeo no Chrome). O `yt-limit` consulta isso uma vez por segundo:

- há player com `PlaybackStatus == Playing` **e** URL/capa do YouTube → soma 1 segundo;
- caso contrário, não conta nada.

Um contador flutuante fica no canto superior direito da tela (`▶ 12:34 / 30:00`), verde
enquanto toca, amarelo nos últimos 5 minutos, vermelho quando bloqueado.

## Requisitos

- Linux com D-Bus de sessão (GNOME, KDE, etc.). Testado no Ubuntu + GNOME Wayland.
- Python 3.10+ com PyGObject e GTK 3 (`sudo apt install python3-gi gir1.2-gtk-3.0`).
- Firefox ou Chrome/Chromium. No Firefox o suporte a MPRIS já vem ligado
  (`media.hardwaremediakeys.enabled`).

Não há dependências pip: o app usa apenas a biblioteca padrão e os bindings GTK do sistema,
por isso roda direto no `python3` do sistema em vez de um venv.

## Instalação

```bash
git clone https://github.com/luiz-nast/yt-limit.git
cd yt-limit
./install.sh
```

Isso copia o pacote para `~/.local/lib/yt-limit`, cria o comando `~/.local/bin/yt-limit` e
instala um serviço systemd de usuário que sobe junto com a sessão gráfica.

```bash
systemctl --user status yt-limit      # está rodando?
journalctl --user -u yt-limit -f      # logs ao vivo
./uninstall.sh                        # remove tudo
```

## Uso

```bash
yt-limit --status        # tempo de hoje e os vídeos mais assistidos
yt-limit --limit 45      # muda o limite diário (minutos); reinicie o serviço depois
yt-limit --reset         # zera o contador de hoje
yt-limit --debug         # roda em primeiro plano logando cada player detectado
yt-limit --no-overlay    # só conta e pausa, sem janelas
```

Config: `~/.config/yt-limit/config.json`. Estado do dia: `~/.local/share/yt-limit/state.json`.

## Limitações conhecidas

- **Vídeo em tela cheia** cobre o contador (janelas fullscreen ficam acima de tudo). A
  contagem e o bloqueio continuam funcionando; só o contador some.
- **Chrome** não expõe a URL da página no MPRIS; a detecção usa a capa (`i.ytimg.com`).
  Funciona para vídeos normais; Shorts sem capa podem não ser detectados.
- **YouTube Music** também conta, pois usa o mesmo domínio de capas.
- Rodar o daemon a partir de um processo confinado por AppArmor (por exemplo, dentro de
  outro snap) falha com *Access denied* ao falar com o Firefox snap. Rode do terminal ou pelo
  serviço systemd, que é o caminho normal.
- Só mede o que o navegador reporta como mídia ativa. Um segundo vídeo tocando em outra
  aba do mesmo Firefox não é contado em dobro (o Firefox expõe um player por processo).
