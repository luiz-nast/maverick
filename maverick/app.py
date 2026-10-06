"""Daemon: a cada segundo consulta o MPRIS, soma tempo se um vídeo do YouTube está
tocando, mostra o contador e pausa ao atingir o limite. A cada minuto confere se o
bloqueio de sites continua aplicado."""

from __future__ import annotations

import logging
import signal
import subprocess
import time

from gi.repository import GLib

from . import blocking
from .a11y import A11y
from .mpris import Mpris, Player
from .store import APP_ID, APP_NAME, CONFIG_FILE, STATE_FILE, Config, State, fmt, mtime, usage_status

log = logging.getLogger("maverick")
BLOCK_CHECK_SECONDS = 60
TIME_UP = "⛔ Tempo esgotado, volte amanhã"


def notify(summary: str, body: str = "", urgency: str = "normal") -> None:
    try:
        subprocess.Popen(["notify-send", "-a", APP_NAME, "-i", APP_ID, "-u", urgency, summary, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class App:
    def __init__(self, show_overlay: bool = True, debug: bool = False) -> None:
        self.config, self._config_mtime = Config.load(), mtime(CONFIG_FILE)
        self.state, self._state_mtime = State.load(), mtime(STATE_FILE)
        self.mpris, self.a11y, self.debug = Mpris(), A11y(), debug
        self.overlay = None
        if show_overlay:
            from .overlay import Overlay  # GTK só quando há janela

            self.overlay = Overlay()
        self._warned = False
        self._block_warned = False
        self._last_status = None
        self._visible_until = 0.0

    @property
    def limit_seconds(self) -> int:
        return self.config.effective_limit() * 60

    @property
    def over_limit(self) -> bool:
        return self.state.seconds >= self.limit_seconds

    def _sync_files(self) -> None:
        """Recarrega config e estado gravados por outro processo (janela, `maverick reset`);
        sem isso o próximo segundo contado sobrescreveria a mudança."""
        if (m := mtime(CONFIG_FILE)) != self._config_mtime:
            self._config_mtime, self.config, self._warned = m, Config.load(), False
        if (m := mtime(STATE_FILE)) != self._state_mtime:
            self._state_mtime, self.state, self._warned = m, State.load(), False
            log.info("Estado alterado por fora; hoje: %s", fmt(self.state.seconds))

    def _save_state(self) -> None:
        self.state.save()
        self._state_mtime = mtime(STATE_FILE)

    def is_youtube(self, p: Player) -> bool:
        """Metadados do MPRIS; para janela privada, a acessibilidade; sem ela, a config."""
        if p.is_youtube or not p.metadata_hidden:
            return p.is_youtube
        verdict = self.a11y.private_media_is_youtube()
        return self.config.count_private_media if verdict is None else verdict

    def tick(self) -> bool:
        self._sync_files()
        if self.state.roll_day():
            log.info("Novo dia, contador zerado.")
            self._warned = False
        try:
            players = [p for p in self.mpris.players() if self.is_youtube(p)]
        except GLib.Error as e:
            log.warning("D-Bus indisponível: %s", e)
            players = []
        if self.debug:
            for p in players:
                log.debug("%s | %s | %s | %s", p.bus_name, p.status, p.title[:50], p.url or p.art_url)
        playing = [p for p in players if p.is_playing]

        if playing and not self.over_limit:
            # Firefox expõe um player por processo: duas abas tocando contam uma vez.
            self.state.add_second(playing[0].title)
            self._save_state()  # a janela lê o arquivo ao vivo
            self._notify_thresholds()
        if playing and self.over_limit:
            for p in playing:
                self.mpris.pause(p)
                log.info("Pausado: %s", p.title)

        status = usage_status(self.state.seconds, self.limit_seconds, bool(playing), self.config.warn_minutes_left)
        if status != self._last_status:
            log.info("%s  %s / %s", status, fmt(self.state.seconds), fmt(self.limit_seconds))
            self._last_status = status
        self._update_overlay(bool(playing), status)
        return True

    def _notify_thresholds(self) -> None:
        left = self.limit_seconds - self.state.seconds
        if left <= 0:
            notify("YouTube: limite de hoje atingido",
                   f"{self.config.effective_limit()} min usados. Volta amanhã.", "critical")
        elif not self._warned and left <= self.config.warn_minutes_left * 60:
            self._warned = True
            notify("YouTube: quase no limite", f"Faltam {fmt(left)} para hoje.")

    def _update_overlay(self, playing: bool, status: str) -> None:
        """Visível só enquanto toca, mais `hide_after_seconds`; estourado o limite,
        cada tentativa de play mostra o aviso pelo mesmo tempo."""
        if not self.overlay:
            return
        now = time.monotonic()
        if playing:
            self._visible_until = now + self.config.hide_after_seconds
        if now >= self._visible_until:
            self.overlay.hide()
        elif self.over_limit:
            self.overlay.show_message(TIME_UP, "blocked")
        else:
            self.overlay.update(self.state.seconds, self.limit_seconds, status)

    def _check_block(self) -> bool:
        """Avisa uma vez se algum site da lista saiu do /etc/hosts."""
        st = blocking.status()
        missing = st.missing(self.config.blocked_sites) if st.helper_installed else []
        if missing and not self._block_warned:
            log.warning("Bloqueio de sites incompleto: %s", ", ".join(missing))
            notify("Bloqueio de sites desativado",
                   f"{len(missing)} site(s) fora do bloqueio. Abra o Maverick e clique em Aplicar.", "critical")
        self._block_warned = bool(missing)
        return True

    def run(self) -> None:
        loop = GLib.MainLoop()
        # Shutdown/restart mandam SIGTERM; sem tratar, o `finally` não roda.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_: loop.quit() or False)
        log.info("Maverick iniciado. Hoje: %s / %s", fmt(self.state.seconds), fmt(self.limit_seconds))
        self.tick()
        self._check_block()
        GLib.timeout_add(1000, self.tick)  # precisão de 1 s: cada tick soma 1 s
        GLib.timeout_add_seconds(BLOCK_CHECK_SECONDS, self._check_block)
        try:
            loop.run()
        finally:
            self._save_state()
            log.info("Encerrando. Estado salvo: %s / %s", fmt(self.state.seconds), fmt(self.limit_seconds))
