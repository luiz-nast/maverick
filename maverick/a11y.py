"""Leitura das abas do navegador pela acessibilidade (AT-SPI).

Em janela privada o Firefox esconde título e URL no MPRIS ("O Firefox está
reproduzindo mídia"). A árvore de acessibilidade continua expondo, por aba:

- o título ("... - YouTube");
- se a janela é privada: o título da janela termina em "— navegação privativa"
  (pt-BR) ou "Private Browsing" (en);
- se a aba está selecionada (estado SELECTED);
- se a aba está tocando som: aparece um botão "Silenciar aba"/"Mute tab" (ou
  "Ativar som da aba"/"Unmute tab" se silenciada) antes do "Fechar aba". Com o
  som bloqueado por autoplay o botão é "Reproduzir som na aba"/"Play tab".

A lista de abas pode ficar desatualizada em janelas que não estão em primeiro
plano (testado no Firefox 156). O título da janela sempre atualiza e contém a aba
selecionada, então ele é a fonte principal; a lista de abas só é usada quando a
aba selecionada nela bate com o título da janela.

Só funciona se o navegador estiver no barramento de acessibilidade. No GNOME isso
exige `toolkit-accessibility` ligado antes de o navegador abrir.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

ATSPI_ACCESSIBLE = "org.a11y.atspi.Accessible"
REGISTRY = "org.a11y.atspi.Registry"
ROOT = "/org/a11y/atspi/accessible/root"
BROWSER_NAMES = ("firefox", "chrom", "brave", "vivaldi", "opera", "edge")
SKIP_ROLES = {"document web", "document frame", "internal frame", "embedded"}  # conteúdo da página
STATE_SELECTED = 23
CACHE_SECONDS = 3
MAX_NODES = 1500
MAX_DEPTH = 14

PRIVATE_MARKERS = (
    "navegação privativa", "navegação privada", "private browsing", "navegación privada",
    "navigation privée", "privater modus", "incognito", "anônima", "inprivate",
)
BLOCKED_AUDIO_LABELS = {"reproduzir som na aba", "play tab", "reproducir pestaña", "lire l’onglet"}
BROWSER_TITLE_SUFFIXES = (" — Mozilla Firefox", " - Mozilla Firefox", " - Google Chrome", " - Chromium", " - Brave")


def looks_like_youtube(title: str, attrs: dict[str, str] | None = None) -> bool:
    n = (title or "").strip().lower()
    if n.endswith("- youtube") or n.endswith("- youtube music") or n == "youtube":
        return True
    for key, value in (attrs or {}).items():
        if key.lower() in ("docurl", "uri", "url") and "youtube.com" in value.lower():
            return True
    return False


def is_private_window(title: str) -> bool:
    t = (title or "").lower()
    return any(m in t for m in PRIVATE_MARKERS)


def selected_title(window_title: str) -> str:
    """Título da aba selecionada a partir do título da janela."""
    for suffix in BROWSER_TITLE_SUFFIXES:
        i = window_title.find(suffix)
        if i >= 0:
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
        if self.tabs_fresh:
            sounding = [t for t in self.tabs if t.audio == "playing"]
            if sounding:
                return any(looks_like_youtube(t.title) for t in sounding)
        return looks_like_youtube(self.selected_title)


def private_media_verdict(windows: list[Window]) -> bool:
    """A mídia sem metadados (janela privada) é do YouTube?

    Considera as janelas privadas (ou todas, se nenhuma for reconhecida como
    privada). Em cada uma: se a lista de abas está em dia e alguma aba toca som,
    decide por ela; senão, pela aba selecionada (título da janela).
    """
    pool = [w for w in windows if w.private] or windows
    return any(w.is_youtube() for w in pool)


class A11y:
    def __init__(self) -> None:
        self.conn: Gio.DBusConnection | None = None
        self._cache_at = 0.0
        self._cache: list[Window] | None = None

    # --- conexão ------------------------------------------------------------
    def _connect(self) -> Gio.DBusConnection | None:
        if self.conn is not None:
            return self.conn
        try:
            session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            addr = session.call_sync(
                "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus", "GetAddress",
                None, GLib.VariantType("(s)"), Gio.DBusCallFlags.NONE, 2000, None,
            ).unpack()[0]
            self.conn = Gio.DBusConnection.new_for_address_sync(
                addr,
                Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
                | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION,
                None, None,
            )
        except GLib.Error:
            self.conn = None
        return self.conn

    def _call(self, bus: str, path: str, iface: str, method: str, args=None, sig: str | None = None):
        return self.conn.call_sync(
            bus, path, iface, method, args,
            GLib.VariantType(sig) if sig else None,
            Gio.DBusCallFlags.NONE, 2000, None,
        ).unpack()

    def _children(self, bus: str, path: str) -> list[tuple[str, str]]:
        return self._call(bus, path, ATSPI_ACCESSIBLE, "GetChildren", None, "(a(so))")[0]

    def _name(self, bus: str, path: str) -> str:
        return self._call(
            bus, path, "org.freedesktop.DBus.Properties", "Get",
            GLib.Variant("(ss)", (ATSPI_ACCESSIBLE, "Name")), "(v)",
        )[0]

    def _role(self, bus: str, path: str) -> str:
        return self._call(bus, path, ATSPI_ACCESSIBLE, "GetRoleName", None, "(s)")[0]

    def _selected(self, bus: str, path: str) -> bool:
        words = self._call(bus, path, ATSPI_ACCESSIBLE, "GetState", None, "(au)")[0]
        return bool(words and words[0] & (1 << STATE_SELECTED))

    def _browser_apps(self) -> list[tuple[str, str, str]] | None:
        """[(nome, bus, path)] dos navegadores no barramento; None sem barramento."""
        if self._connect() is None:
            return None
        try:
            apps = self._children(REGISTRY, ROOT)
        except GLib.Error:
            self.conn = None
            return None
        found = []
        for bus, path in apps:
            try:
                name = self._name(bus, path)
            except GLib.Error:
                continue
            if any(b in name.lower() for b in BROWSER_NAMES):
                found.append((name, bus, path))
        return found

    # --- consulta -----------------------------------------------------------
    def browsers_on_bus(self) -> list[str]:
        return [name for name, _, _ in (self._browser_apps() or [])]

    def windows(self) -> list[Window] | None:
        """Janelas de todos os navegadores no barramento. None se nenhum estiver lá."""
        now = time.monotonic()
        if now - self._cache_at < CACHE_SECONDS:
            return self._cache
        apps = self._browser_apps()
        result: list[Window] | None = None
        if apps:
            result = []
            for _name, bus, path in apps:
                try:
                    frames = self._children(bus, path)
                except GLib.Error:
                    continue
                for fb, fp in frames:
                    try:
                        if self._role(fb, fp) != "frame":
                            continue
                        title = self._name(fb, fp)
                    except GLib.Error:
                        continue
                    result.append(Window(title, is_private_window(title), self._frame_tabs(fb, fp)))
        self._cache, self._cache_at = result, now
        return result

    def private_media_is_youtube(self) -> bool | None:
        windows = self.windows()
        if windows is None:
            return None
        return private_media_verdict(windows)

    def _frame_tabs(self, bus: str, path: str) -> list[Tab]:
        tabs: list[Tab] = []
        queue = [(bus, path, 0)]
        visited = 0
        while queue and visited < MAX_NODES:
            b, p, depth = queue.pop(0)
            visited += 1
            try:
                role = self._role(b, p)
                if role in SKIP_ROLES:
                    continue
                if role == "page tab":
                    tabs.append(self._tab(b, p))
                    continue
                if depth < MAX_DEPTH:
                    queue.extend((cb, cp, depth + 1) for cb, cp in self._children(b, p))
            except GLib.Error:
                continue
        return tabs

    def _tab(self, bus: str, path: str) -> Tab:
        buttons = []
        for cb, cp in self._children(bus, path):
            try:
                if self._role(cb, cp) == "push button":
                    buttons.append(self._name(cb, cp).strip().lower())
            except GLib.Error:
                continue
        audio = None
        if len(buttons) >= 2:  # [botão de som, fechar aba]
            audio = "blocked" if buttons[0] in BLOCKED_AUDIO_LABELS else "playing"
        return Tab(self._name(bus, path), self._selected(bus, path), audio)
