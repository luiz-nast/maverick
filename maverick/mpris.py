"""Players de mídia via MPRIS (D-Bus).

Firefox e Chrome publicam a mídia da página como um player MPRIS. PlaybackStatus
diz se está tocando de fato; os metadados (xesam:url no Firefox, mpris:artUrl no
Chrome) dizem se é YouTube. Em janela privada os metadados vêm vazios.

Vídeo do YouTube embutido em outra página (prévia na busca do Google, DuckDuckGo)
chega com a URL da página. O vídeo aparece nela mesmo assim: o Google põe o ID no
fragmento (`#...vid:v12vqnb0dAE`), outros levam o link do YouTube nos parâmetros.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

from gi.repository import GLib

from . import dbus

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
BROWSERS = ("firefox", "chrom", "brave", "vivaldi", "opera", "edge")
YOUTUBE_RE = re.compile(
    r"(^|[./])(youtube\.com|youtu\.be|youtube-nocookie\.com|ytimg\.com|googlevideo\.com)(/|$)", re.IGNORECASE
)
# YouTube citado dentro da URL de outra página (já decodificada).
EMBEDDED_YOUTUBE_RE = re.compile(
    r"youtube(-nocookie)?\.com/(watch|embed|shorts|live)\b|youtu\.be/[\w-]{11}|[#&,]vid:[\w-]{11}(?![\w-])", re.IGNORECASE
)


@dataclass
class Player:
    bus_name: str
    status: str  # Playing | Paused | Stopped
    title: str
    url: str
    art_url: str

    @property
    def is_playing(self) -> bool:
        return self.status == "Playing"

    @property
    def is_youtube(self) -> bool:
        if any(YOUTUBE_RE.search(u) for u in (self.url, self.art_url) if u):
            return True
        return bool(self.url and EMBEDDED_YOUTUBE_RE.search(unquote(unquote(self.url))))

    @property
    def metadata_hidden(self) -> bool:
        """Navegador sem URL da página: janela privada do Firefox, ou o Chrome, que nunca
        manda a URL e entrega a capa como arquivo local."""
        return (not self.url and not self.art_url.startswith(("http://", "https://"))
                and any(b in self.bus_name.lower() for b in BROWSERS))


class Mpris:
    def __init__(self) -> None:
        self.bus = dbus.session()

    def players(self) -> list[Player]:
        names = dbus.call(self.bus, "org.freedesktop.DBus", "/org/freedesktop/DBus",
                          "org.freedesktop.DBus", "ListNames", reply="(as)")[0]
        found = []
        for name in names:
            if not name.startswith(PREFIX):
                continue
            try:
                props = dbus.call(self.bus, name, PATH, "org.freedesktop.DBus.Properties", "GetAll",
                                  GLib.Variant("(s)", (PLAYER,)), "(a{sv})")[0]
            except GLib.Error:
                continue  # sumiu no meio do caminho ou acesso negado
            meta = props.get("Metadata") or {}
            fields = (str(meta.get(k) or "") for k in ("xesam:title", "xesam:url", "mpris:artUrl"))
            found.append(Player(name, str(props.get("PlaybackStatus", "Stopped")), *fields))
        return found

    def pause(self, player: Player) -> None:
        try:
            dbus.call(self.bus, player.bus_name, PATH, PLAYER, "Pause")
        except GLib.Error:
            pass
