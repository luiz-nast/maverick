"""Daemon: a cada segundo consulta o MPRIS, soma tempo se houver vídeo do YouTube
tocando, atualiza o contador e pausa ao atingir o limite. Também vigia se o
bloqueio de sites continua aplicado."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time

from gi.repository import GLib

from . import blocking
from .a11y import A11y
from .mpris import Mpris, Player
from .store import APP_ID, APP_NAME, CONFIG_FILE, Config, State, fmt

log = logging.getLogger("maverick")


def notify(summary: str, body: str = "", urgency: str = "normal") -> None:
    if shutil.which("notify-send"):
        subprocess.Popen(
            ["notify-send", "-a", APP_NAME, "-i", APP_ID, "-u", urgency, summary, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


class App:
    SAVE_EVERY = 5  # segundos, quando nada mudou
    BLOCK_CHECK_EVERY = 60  # segundos

    def __init__(self, show_overlay: bool = True, debug: bool = False) -> None:
        self.config = Config.load()
        self._config_mtime = self._mtime()
        self.state = State.load()
        self.mpris = Mpris()
        self.a11y = A11y()
        self.debug = debug
        self._private_fallback_logged = False
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
        self._dirty = False
        self._block_ticks = self.BLOCK_CHECK_EVERY  # checa no primeiro tick
        self._block_warned = False

    # --- helpers ---------------------------------------------------------
    @staticmethod
    def _mtime() -> float:
        try:
            return CONFIG_FILE.stat().st_mtime
        except OSError:
            return 0.0

    def _reload_config_if_changed(self) -> None:
        """A janela grava a config; o daemon aplica sem precisar reiniciar."""
        mtime = self._mtime()
        if mtime != self._config_mtime:
            self._config_mtime = mtime
            old_today, old_target = self.config.effective_limit(), self.config.limit_minutes
            self.config = Config.load()
            new_today = self.config.effective_limit()
            if new_today != old_today:
                log.info("Limite de hoje: %d -> %d min", old_today, new_today)
                self._warned = False
            if self.config.limit_minutes != old_target and self.config.limit_minutes > new_today:
                log.info("Limite de %d min agendado para amanhã", self.config.limit_minutes)

    @property
    def limit_seconds(self) -> int:
        return self.config.effective_limit() * 60

    @property
    def over_limit(self) -> bool:
        return self.state.seconds >= self.limit_seconds

    def is_youtube(self, p: Player) -> bool:
        """Camadas: URL/capa do MPRIS; senão, árvore de acessibilidade; senão, fallback."""
        if p.is_youtube:
            return True
        if not p.metadata_hidden:
            return False
        verdict = self.a11y.private_media_is_youtube()
        if verdict is not None:
            return verdict
        if self.config.count_private_media and not self._private_fallback_logged:
            self._private_fallback_logged = True
            log.info(
                "Mídia em janela privada sem metadados e navegador fora do barramento "
                "de acessibilidade: contando como YouTube (count_private_media=true)."
            )
        return self.config.count_private_media

    def youtube_players(self) -> list[Player]:
        try:
            return [p for p in self.mpris.players() if self.is_youtube(p)]
        except GLib.Error as e:
            log.warning("D-Bus indisponível: %s", e)
            return []

    # --- loop ------------------------------------------------------------
    def tick(self) -> bool:
        self._reload_config_if_changed()
        if self.state.roll_day():
            log.info("Novo dia, contador zerado.")
            self._warned = False
            self._paused_titles.clear()
            self._dirty = True

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
            self._dirty = True
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

        # Grava a cada segundo contado (a janela lê o arquivo ao vivo) e, parado,
        # no máximo a cada SAVE_EVERY segundos.
        self._ticks_since_save += 1
        if self._dirty or self._ticks_since_save >= self.SAVE_EVERY:
            if self._dirty:
                self.state.save()
            self._dirty = False
            self._ticks_since_save = 0

        self._block_ticks += 1
        if self._block_ticks >= self.BLOCK_CHECK_EVERY:
            self._block_ticks = 0
            self._check_block()
        return True

    def _check_block(self) -> None:
        """Avisa uma vez se o bloqueio de sites foi removido ou está desatualizado."""
        st = blocking.status()
        if not st.helper_installed:
            return
        missing = st.missing(self.config.blocked_sites)
        if missing and not self._block_warned:
            self._block_warned = True
            log.warning("Bloqueio de sites incompleto: %s", ", ".join(missing))
            notify(
                "Bloqueio de sites desativado",
                f"{len(missing)} site(s) fora do bloqueio. Abra o Maverick e clique em Aplicar.",
                urgency="critical",
            )
        elif not missing:
            self._block_warned = False

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
            f"{self.config.effective_limit()} min usados. Volta amanhã.",
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
            "Maverick iniciado. Hoje: %s / %s",
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
