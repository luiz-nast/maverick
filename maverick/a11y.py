"""Abas do navegador pela acessibilidade (AT-SPI), para mídia de janela privada.

Em janela privada o Firefox esconde título e URL no MPRIS. A acessibilidade expõe:

- o título da janela: aba selecionada + "— navegação privativa" (pt-BR) ou
  "Private Browsing" (en);
- a lista de abas: título, estado SELECTED e o botão de som ("Silenciar aba"/
  "Mute tab" tocando, "Reproduzir som na aba"/"Play tab" com autoplay bloqueado).

O Firefox pode deixar a lista de abas parada em janela fora de foco (visto no
Firefox 156); o título da janela sempre atualiza. Por isso a lista só é usada
quando a aba selecionada nela bate com o título da janela.

Exige o navegador no barramento de acessibilidade: no GNOME, `toolkit-accessibility`
ligado antes de o navegador abrir.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

from gi.repository import Gio, GLib

from . import dbus
from .mpris import BROWSERS

ACCESSIBLE = "org.a11y.atspi.Accessible"
SKIP_ROLES = {"document web", "document frame", "internal frame", "embedded"}  # conteúdo da página
STATE_SELECTED = 23
TIMEOUT = 1000
CACHE_SECONDS = 3
MAX_NODES = 1500
MAX_DEPTH = 14

PRIVATE_MARKERS = ("navegação privativa", "navegação privada", "private browsing", "navegación privada",
                   "navigation privée", "privater modus", "incognito", "anônima", "inprivate")
BLOCKED_AUDIO = {"reproduzir som na aba", "play tab", "reproducir pestaña", "lire l’onglet"}
TITLE_SUFFIXES = (" — Mozilla Firefox", " - Mozilla Firefox", " - Google Chrome", " - Chromium", " - Brave")


def looks_like_youtube(title: str) -> bool:
    t = (title or "").strip().lower()
    return t == "youtube" or t.endswith(("- youtube", "- youtube music"))


def is_private_window(title: str) -> bool:
    t = (title or "").lower()
    return any(m in t for m in PRIVATE_MARKERS)


def selected_title(window_title: str) -> str:
    """Título da aba selecionada a partir do título da janela."""
    for suffix in TITLE_SUFFIXES:
        if (i := window_title.find(suffix)) >= 0:
            return window_title[:i]
    return "" if window_title.lower().startswith("mozilla firefox") else window_title


@dataclass
class Tab:
    title: str
    selected: bool
    audio: str | None  # "playing" (inclui silenciada), "blocked" ou None


@dataclass
class Window:
    title: str
    private: bool
    tabs: list[Tab]

    @property
    def selected_title(self) -> str:
        return selected_title(self.title)

    @property
    def tabs_fresh(self) -> bool:
        sel = self.selected_title.strip()
        return bool(sel) and any(t.selected and t.title.strip() == sel for t in self.tabs)

    def is_youtube(self) -> bool:
        sounding = [t for t in self.tabs if t.audio == "playing"] if self.tabs_fresh else []
        titles = [t.title for t in sounding] or [self.selected_title]
        return any(map(looks_like_youtube, titles))


def private_media_verdict(windows: list[Window]) -> bool:
    """A mídia de janela privada é do YouTube? Considera só janelas privadas (ou todas,
    se nenhuma for reconhecida): a aba tocando som decide; senão, a selecionada."""
    return any(w.is_youtube() for w in ([w for w in windows if w.private] or windows))


class A11y:
    def __init__(self) -> None:
        self.conn: Gio.DBusConnection | None = None
        self._cache_at = 0.0
        self._cache: list[Window] | None = None
        self._app_names: dict[str, str | None] = {}  # bus -> nome (None = ignorar)

    def _connect(self) -> Gio.DBusConnection | None:
        if self.conn is None:
            try:
                addr = dbus.call(dbus.session(), "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus",
                                 "GetAddress", reply="(s)", timeout=TIMEOUT)[0]
                self.conn = Gio.DBusConnection.new_for_address_sync(
                    addr, Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                    | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, None, None)
            except GLib.Error:
                pass
        return self.conn

    def _call(self, bus: str, path: str, method: str, reply: str):
        return dbus.call(self.conn, bus, path, ACCESSIBLE, method, reply=reply, timeout=TIMEOUT)[0]

    def _children(self, bus: str, path: str) -> list[tuple[str, str]]:
        return self._call(bus, path, "GetChildren", "(a(so))")

    def _role(self, bus: str, path: str) -> str:
        return self._call(bus, path, "GetRoleName", "(s)")

    def _name(self, bus: str, path: str) -> str:
        return dbus.get_property(self.conn, bus, path, ACCESSIBLE, "Name", TIMEOUT)

    def _app_name(self, bus: str, path: str) -> str | None:
        """Nome do app, guardado por conexão. O próprio processo é ignorado: com a
        acessibilidade ligada a janela GTK do Maverick também está no barramento, e
        perguntar a si mesmo de forma síncrona trava até o timeout."""
        if bus not in self._app_names:
            try:
                pid = dbus.call(self.conn, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                "GetConnectionUnixProcessID", GLib.Variant("(s)", (bus,)), "(u)")[0]
                self._app_names[bus] = None if pid == os.getpid() else self._name(bus, path)
            except GLib.Error:
                return None  # tenta de novo na próxima varredura
        return self._app_names[bus]

    def _browser_apps(self) -> list[tuple[str, str, str]]:
        """[(nome, bus, path)] dos navegadores no barramento de acessibilidade."""
        if self._connect() is None:
            return []
        try:
            apps = self._children("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")
        except GLib.Error:
            self.conn, self._app_names = None, {}
            return []
        found = []
        for bus, path in apps:
            name = self._app_name(bus, path)
            if name and any(b in name.lower() for b in BROWSERS):
                found.append((name, bus, path))
        return found

    def browsers_on_bus(self) -> list[str]:
        return [name for name, _, _ in self._browser_apps()]

    def windows(self) -> list[Window] | None:
        """Janelas dos navegadores no barramento; None se nenhum estiver lá."""
        if time.monotonic() - self._cache_at >= CACHE_SECONDS:
            self._cache = None
            for _name, bus, path in self._browser_apps():
                self._cache = self._cache or []
                try:
                    frames = self._children(bus, path)
                except GLib.Error:
                    continue
                for fb, fp in frames:
                    try:
                        if self._role(fb, fp) == "frame":
                            title = self._name(fb, fp)
                            self._cache.append(Window(title, is_private_window(title), self._tabs(fb, fp)))
                    except GLib.Error:
                        continue
            self._cache_at = time.monotonic()
        return self._cache

    def private_media_is_youtube(self) -> bool | None:
        windows = self.windows()
        return None if windows is None else private_media_verdict(windows)

    def _tabs(self, bus: str, path: str) -> list[Tab]:
        tabs, queue, visited = [], [(bus, path, 0)], 0
        while queue and visited < MAX_NODES:
            b, p, depth = queue.pop(0)
            visited += 1
            try:
                role = self._role(b, p)
                if role == "page tab":
                    tabs.append(self._tab(b, p))
                elif role not in SKIP_ROLES and depth < MAX_DEPTH:
                    queue.extend((cb, cp, depth + 1) for cb, cp in self._children(b, p))
            except GLib.Error:
                continue
        return tabs

    def _tab(self, bus: str, path: str) -> Tab:
        buttons = [self._name(cb, cp).strip().lower() for cb, cp in self._children(bus, path)
                   if self._role(cb, cp) == "push button"]
        audio = None
        if len(buttons) >= 2:  # [botão de som, fechar aba]
            audio = "blocked" if buttons[0] in BLOCKED_AUDIO else "playing"
        state = self._call(bus, path, "GetState", "(au)")
        return Tab(self._name(bus, path), bool(state and state[0] >> STATE_SELECTED & 1), audio)
