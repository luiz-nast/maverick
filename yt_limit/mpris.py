"""Leitura dos players de mídia via MPRIS (D-Bus).

Firefox e Chrome/Chromium publicam um player MPRIS por janela/processo quando
uma página tem mídia ativa. Pelo PlaybackStatus sabemos se o vídeo está de fato
tocando (e não apenas com a aba aberta), e pelos metadados (xesam:url no Firefox,
mpris:artUrl no Chrome) sabemos se a página é do YouTube.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

MPRIS_PREFIX = "org.mpris.MediaPlayer2."
MPRIS_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"

YOUTUBE_RE = re.compile(
    r"(^|[./])(youtube\.com|youtu\.be|youtube-nocookie\.com|ytimg\.com|googlevideo\.com)(/|$)",
    re.IGNORECASE,
)


@dataclass
class Player:
    bus_name: str
    status: str  # Playing | Paused | Stopped
    title: str
    url: str
    art_url: str

    @property
    def is_youtube(self) -> bool:
        for candidate in (self.url, self.art_url):
            if candidate and YOUTUBE_RE.search(candidate):
                return True
        return False

    @property
    def is_playing(self) -> bool:
        return self.status == "Playing"


class Mpris:
    def __init__(self) -> None:
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def _list_names(self) -> list[str]:
        reply = self.bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "ListNames",
            None,
            GLib.VariantType("(as)"),
            Gio.DBusCallFlags.NONE,
            1000,
            None,
        )
        return [n for n in reply.unpack()[0] if n.startswith(MPRIS_PREFIX)]

    def players(self) -> list[Player]:
        found: list[Player] = []
        for name in self._list_names():
            try:
                reply = self.bus.call_sync(
                    name,
                    MPRIS_PATH,
                    "org.freedesktop.DBus.Properties",
                    "GetAll",
                    GLib.Variant("(s)", (PLAYER_IFACE,)),
                    GLib.VariantType("(a{sv})"),
                    Gio.DBusCallFlags.NONE,
                    1000,
                    None,
                )
            except GLib.Error:
                # Player sumiu no meio do caminho ou acesso negado: ignora.
                continue
            props = reply.unpack()[0]
            meta = props.get("Metadata") or {}
            found.append(
                Player(
                    bus_name=name,
                    status=str(props.get("PlaybackStatus", "Stopped")),
                    title=str(meta.get("xesam:title", "") or ""),
                    url=str(meta.get("xesam:url", "") or ""),
                    art_url=str(meta.get("mpris:artUrl", "") or ""),
                )
            )
        return found

    def pause(self, player: Player) -> None:
        try:
            self.bus.call_sync(
                player.bus_name,
                MPRIS_PATH,
                PLAYER_IFACE,
                "Pause",
                None,
                None,
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
        except GLib.Error:
            pass
