"""Loop principal: a cada segundo consulta o MPRIS, soma tempo se houver vídeo
do YouTube tocando, atualiza o contador e bloqueia ao atingir o limite."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

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


class App:
    SAVE_EVERY = 5  # segundos

    def __init__(self, show_overlay: bool = True, debug: bool = False) -> None:
        self.config = Config.load()
        self.state = State.load()
        self.mpris = Mpris()
        self.debug = debug
        self.overlay = None
        if show_overlay:
            from .overlay import Overlay  # GTK só quando há janela

            self.overlay = Overlay()
        self._ticks_since_save = 0
        self._warned = False
        self._last_status = None
        self._paused_titles: set[str] = set()
        # Até quando a pílula deve continuar visível (monotonic).
        self._visible_until = 0.0

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
            self._warned = False
            self._paused_titles.clear()

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

        self._update_overlay(playing, status)

        self._ticks_since_save += 1
        if self._ticks_since_save >= self.SAVE_EVERY:
            self._ticks_since_save = 0
            self.state.save()
        return True

    def _update_overlay(self, playing: list[Player], status: str) -> None:
        """Pílula visível só enquanto toca, mais `hide_after_seconds` depois de parar.
        Com o limite estourado, cada tentativa de play mostra o aviso pelo mesmo tempo."""
        if not self.overlay:
            return
        now = time.monotonic()
        if playing:
            self._visible_until = now + self.config.hide_after_seconds
        if now >= self._visible_until:
            self.overlay.hide()
            return
        if self.over_limit:
            self.overlay.show_message("⛔ Tempo esgotado, volte amanhã", "blocked")
        else:
            self.overlay.update(self.state.seconds, self.limit_seconds, status)

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
        self._enforce(playing)

    def _enforce(self, playing: list[Player]) -> None:
        for p in playing:
            self.mpris.pause(p)
            if p.title not in self._paused_titles:
                log.info("Pausado: %s", p.title)
                self._paused_titles.add(p.title)

    def run(self) -> None:
        import signal

        loop = GLib.MainLoop()
        # Shutdown/restart mandam SIGTERM; sem isso o Python morre sem passar
        # pelo `finally` e perde os últimos segundos não salvos.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_: (loop.quit(), False)[1])
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
            log.info("Encerrando. Estado salvo: %s / %s", fmt(self.state.seconds), fmt(self.limit_seconds))
