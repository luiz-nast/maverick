"""Pílula sempre no topo, no canto superior direito: `▶ 12:34 / 30:00`."""

from __future__ import annotations

import os

# No GNOME Wayland janela nativa não pode pedir "sempre no topo"; via XWayland o
# Mutter respeita _NET_WM_STATE_ABOVE.
os.environ.setdefault("GDK_BACKEND", "x11")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .store import fmt  # noqa: E402

CSS = b"""
.pill { background-color: rgba(20, 20, 20, 0.88); color: #ffffff; border-radius: 14px;
        padding: 6px 14px; font-family: monospace; font-size: 15px; font-weight: bold; }
.pill.idle    { color: #bdbdbd; }
.pill.playing { color: #7CFC9A; }
.pill.warning { color: #FFD166; }
.pill.blocked { color: #FF6B6B; }
"""
ICONS = {"playing": "▶", "warning": "▶", "blocked": "⛔", "idle": "⏸"}
MARGIN = 12


class Overlay(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(title="Maverick", decorated=False, resizable=False, accept_focus=False,
                         skip_taskbar_hint=True, skip_pager_hint=True, type_hint=Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.stick()
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        screen = self.get_screen()
        if (visual := screen.get_rgba_visual()) and screen.is_composited():
            self.set_visual(visual)  # cantos arredondados transparentes
        self.set_app_paintable(True)
        self.label = Gtk.Label()
        self.label.get_style_context().add_class("pill")
        self.add(self.label)
        self._state = ""
        self.connect("size-allocate", lambda *_: self._place())
        self.connect("delete-event", lambda *_: True)  # não deixa fechar

    def _place(self) -> None:
        # Área de trabalho: desconta a barra superior e o dock do GNOME.
        display = Gdk.Display.get_default()
        area = (display.get_primary_monitor() or display.get_monitor(0)).get_workarea()
        self.move(area.x + area.width - self.get_size()[0] - MARGIN, area.y + MARGIN)

    def update(self, used: int, limit: int, state: str) -> None:
        self.show_message(f"{ICONS[state]} {fmt(used)} / {fmt(limit)}", state)

    def show_message(self, text: str, state: str) -> None:
        self.label.set_text(text)
        ctx = self.label.get_style_context()
        if self._state:
            ctx.remove_class(self._state)
        ctx.add_class(state)
        self._state = state
        if not self.get_visible():
            self.show_all()
        self._place()
