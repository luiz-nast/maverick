"""Consulta à árvore de acessibilidade (AT-SPI) para saber se um navegador tem
alguma aba do YouTube aberta.

Serve para janelas privadas: nelas o Firefox e o Chrome escondem título e URL no
MPRIS, mas a acessibilidade continua expondo o título de cada aba ("... - YouTube").
Só funciona se o navegador estiver registrado no barramento de acessibilidade, o
que no GNOME exige `toolkit-accessibility` ligado antes de o navegador abrir.
"""

from __future__ import annotations

import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

ATSPI_ACCESSIBLE = "org.a11y.atspi.Accessible"
REGISTRY = "org.a11y.atspi.Registry"
ROOT = "/org/a11y/atspi/accessible/root"
BROWSER_NAMES = ("firefox", "chrom", "brave", "vivaldi", "opera", "edge")
DOCUMENT_ROLES = {"document web", "document frame", "embedded", "internal frame"}
CACHE_SECONDS = 5
MAX_NODES = 800
MAX_DEPTH = 12


def looks_like_youtube(name: str, attrs: dict[str, str]) -> bool:
    n = (name or "").strip().lower()
    if n.endswith("- youtube") or n.endswith("- youtube music") or n == "youtube":
        return True
    for key, value in attrs.items():
        if key.lower() in ("docurl", "uri", "url") and "youtube.com" in value.lower():
            return True
    return False


class A11y:
    def __init__(self) -> None:
        self.conn: Gio.DBusConnection | None = None
        self._cache_at = 0.0
        self._cache: bool | None = None

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

    def _attrs(self, bus: str, path: str) -> dict[str, str]:
        try:
            return self._call(bus, path, ATSPI_ACCESSIBLE, "GetAttributes", None, "(a{ss})")[0]
        except GLib.Error:
            return {}

    # --- consulta -----------------------------------------------------------
    def browsers_on_bus(self) -> list[str]:
        """Nomes dos navegadores registrados no barramento de acessibilidade."""
        if self._connect() is None:
            return []
        try:
            apps = self._children(REGISTRY, ROOT)
            names = []
            for bus, path in apps:
                try:
                    n = self._name(bus, path)
                except GLib.Error:
                    continue
                if any(b in n.lower() for b in BROWSER_NAMES):
                    names.append(n)
            return names
        except GLib.Error:
            self.conn = None
            return []

    def browser_has_youtube(self) -> bool | None:
        """True/False se algum navegador no barramento tem aba do YouTube.
        None se nenhum navegador está no barramento (não dá para saber)."""
        now = time.monotonic()
        if now - self._cache_at < CACHE_SECONDS:
            return self._cache
        self._cache = self._scan()
        self._cache_at = now
        return self._cache

    def _scan(self) -> bool | None:
        if self._connect() is None:
            return None
        try:
            apps = self._children(REGISTRY, ROOT)
        except GLib.Error:
            self.conn = None
            return None
        found_browser = False
        for bus, path in apps:
            try:
                if not any(b in self._name(bus, path).lower() for b in BROWSER_NAMES):
                    continue
            except GLib.Error:
                continue
            found_browser = True
            if self._app_has_youtube(bus, path):
                return True
        return False if found_browser else None

    def _app_has_youtube(self, bus: str, path: str) -> bool:
        queue = [(bus, path, 0)]
        visited = 0
        while queue and visited < MAX_NODES:
            b, p, depth = queue.pop(0)
            visited += 1
            try:
                role = self._role(b, p)
                if role in DOCUMENT_ROLES:
                    if looks_like_youtube(self._name(b, p), self._attrs(b, p)):
                        return True
                    continue  # não desce para dentro da página
                if role in ("frame", "window") and looks_like_youtube(self._name(b, p), {}):
                    return True  # título da janela = título da aba ativa
                if depth < MAX_DEPTH:
                    queue.extend((cb, cp, depth + 1) for cb, cp in self._children(b, p))
            except GLib.Error:
                continue
        return False
