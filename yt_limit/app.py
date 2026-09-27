"""Loop principal: a cada segundo consulta o MPRIS, soma tempo se houver vídeo
do YouTube tocando, atualiza o contador e bloqueia ao atingir o limite."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timedelta

from gi.repository import GLib

from .mpris import Mpris, Player
from .store import Config, State, fmt

log = logging.getLogger("yt-limit")


def notify(summary: str, body: str = "", urgency: str = "normal") -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(
            ["notify-send", "-a", "yt-limit", "-u", urgency, summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def until_midnight() -> str:
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    left = int((midnight - now).total_seconds())
    return f"{left // 3600}h{(left % 3600) // 60:02d}"


class App:
    SAVE_EVERY = 5  # segundos

    def __init__(self, show_overlay: bool = True, debug: bool = False) -> None:
        self.config = Config.load()
        self.state = State.load()
        self.mpris = Mpris()
        self.debug = debug
        self.overlay = self.block = None
        if show_overlay:
            from .overlay import BlockScreen, Overlay  # GTK só quando há janela

            self.overlay = Overlay()
            self.block = BlockScreen()
        self._ticks_since_save = 0
        self._warned = False
        self._blocked_notified = False
        self._last_status = None
        self._paused_titles: set[str] = set()

    # --- helpers ---------------------------------------------------------
    @property
    def limit_seconds(self) -> int:
        return self.config.limit_minutes * 60

    @property
    def over_limit(self) -> bool:
        return self.state.seconds >= self.limit_seconds

    def youtube_players(self) -> list[Player]:
        try:
            return [p for p in self.mpris.players() if p.is_youtube]
        except GLib.Error as e:
            log.warning("D-Bus indisponível: %s", e)
            return []

    # --- loop ------------------------------------------------------------
    def tick(self) -> bool:
        if self.state.roll_day():
            log.info("Novo dia, contador zerado.")
            self._warned = self._blocked_notified = False
            self._paused_titles.clear()
            if self.block:
                self.block.hide()

        players = self.youtube_players()
        playing = [p for p in players if p.is_playing]

        if self.debug:
            for p in players:
                log.debug("%s | %s | %s | %s", p.bus_name, p.status, p.title[:50], p.url or p.art_url)

        if self.over_limit:
            self._enforce(playing)
        elif playing:
            # Um segundo tocando. Firefox expõe um player por processo, então
            # duas abas tocando ao mesmo tempo contam uma vez só, o que é o certo.
            self.state.add_second(playing[0].title)
            self._maybe_warn()
            if self.over_limit:
                self._on_limit_reached(playing)

        status = "playing" if playing else "idle"
        if self.over_limit:
            status = "blocked"
        elif playing and self.limit_seconds - self.state.seconds <= self.config.warn_minutes_left * 60:
            status = "warning"
        if status != self._last_status:
            log.info("%s  %s / %s", status, fmt(self.state.seconds), fmt(self.limit_seconds))
            self._last_status = status

        if self.overlay:
            if players or self.config.always_show_overlay or self.over_limit:
                self.overlay.update(self.state.seconds, self.limit_seconds, status)
            else:
                self.overlay.hide()

        self._ticks_since_save += 1
        if self._ticks_since_save >= self.SAVE_EVERY:
            self._ticks_since_save = 0
            self.state.save()
        return True

    def _maybe_warn(self) -> None:
        left = self.limit_seconds - self.state.seconds
        if not self._warned and 0 < left <= self.config.warn_minutes_left * 60:
            self._warned = True
            notify("YouTube: quase no limite", f"Faltam {fmt(left)} para hoje.")

    def _on_limit_reached(self, playing: list[Player]) -> None:
        self.state.save()
        notify(
            "YouTube: limite de hoje atingido",
            f"{self.config.limit_minutes} min usados. Volta amanhã.",
            urgency="critical",
        )
        self._blocked_notified = True
        self._enforce(playing)

    def _enforce(self, playing: list[Player]) -> None:
        for p in playing:
            self.mpris.pause(p)
            if p.title not in self._paused_titles:
                log.info("Pausado: %s", p.title)
                self._paused_titles.add(p.title)
        if self.block and playing:
            self.block.show_blocked(self.state.seconds, self.limit_seconds, until_midnight())
        elif self.block and not self.block.dismissed and not self.block.get_visible():
            # Primeira vez que estoura: mostra mesmo sem player tocando.
            self.block.show_blocked(self.state.seconds, self.limit_seconds, until_midnight())

    def run(self) -> None:
        loop = GLib.MainLoop()
        log.info(
            "yt-limit iniciado. Hoje: %s / %s",
            fmt(self.state.seconds),
            fmt(self.limit_seconds),
        )
        self.tick()
        GLib.timeout_add(1000, self.tick)
        try:
            loop.run()
        finally:
            self.state.save()
