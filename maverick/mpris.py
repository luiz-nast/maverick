"""Players de mídia via MPRIS (D-Bus).

Firefox e Chrome publicam a mídia da página como um player MPRIS. PlaybackStatus
diz se está tocando de fato; os metadados (xesam:url no Firefox, mpris:artUrl no
Chrome) dizem se é YouTube. Em janela privada os metadados vêm vazios.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from gi.repository import GLib

from . import dbus

PREFIX = "org.mpris.MediaPlayer2."
PATH = "/org/mpris/MediaPlayer2"
PLAYER = "org.mpris.MediaPlayer2.Player"
BROWSERS = ("firefox", "chrom", "brave", "vivaldi", "opera", "edge")
YOUTUBE_RE = re.compile(
    r"(^|[./])(youtube\.com|youtu\.be|youtube-nocookie\.com|ytimg\.com|googlevideo\.com)(/|$)", re.IGNORECASE
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
        return any(YOUTUBE_RE.search(u) for u in (self.url, self.art_url) if u)

    @property
    def metadata_hidden(self) -> bool:
        """Navegador sem URL nem capa: é como a mídia de janela privada aparece."""
        return not (self.url or self.art_url) and any(b in self.bus_name.lower() for b in BROWSERS)


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
