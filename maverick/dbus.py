"""Chamadas D-Bus síncronas (Gio), usadas pelo MPRIS e pela acessibilidade."""

from __future__ import annotations

import time

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


def session() -> Gio.DBusConnection:
    return Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(conn, dest: str, path: str, iface: str, method: str,
         args: GLib.Variant | None = None, reply: str | None = None, timeout: int = 1000) -> tuple:
    """Chama um método e devolve a resposta desempacotada. Falhas sobem como GLib.Error."""
    return conn.call_sync(dest, path, iface, method, args, GLib.VariantType(reply) if reply else None,
                          Gio.DBusCallFlags.NONE, timeout, None).unpack()


class Strikes:
    """Quarentena de quem não responde: só depois de `limit` falhas seguidas, zerada a cada
    sucesso. Uma demora isolada do navegador de verdade não o deixa de fora."""

    def __init__(self, seconds: float = 60, limit: int = 3) -> None:
        self.seconds, self.limit = seconds, limit
        self._fails: dict[str, int] = {}
        self._until: dict[str, float] = {}

    def blocked(self, key: str) -> bool:
        return self._until.get(key, 0) > time.monotonic()

    def ok(self, key: str) -> None:
        self._fails.pop(key, None)

    def fail(self, key: str) -> None:
        self._fails[key] = n = self._fails.get(key, 0) + 1
        if n >= self.limit:
            self._until[key] = time.monotonic() + self.seconds


def get_property(conn, dest: str, path: str, iface: str, name: str, timeout: int = 1000):
    return call(conn, dest, path, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (iface, name)), "(v)", timeout)[0]
