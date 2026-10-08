"""Janelas sempre no topo: a pílula do contador no canto superior direito
(`▶ 12:34 / 30:00`) e a tela que cobre a área de trabalho quando um site bloqueado
está em foco."""

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
.cover { background-color: rgba(12, 12, 16, 0.96); color: #ffffff; }
.cover-title { font-size: 40px; font-weight: 800; color: #FF6B6B; }
.cover-text  { font-size: 20px; }
.cover-hint  { font-size: 14px; color: #9a9a9a; }
"""
ICONS = {"playing": "▶", "warning": "▶", "blocked": "⛔", "idle": "⏸"}
MARGIN = 12
_css_done = False


def _workarea() -> Gdk.Rectangle:
    """Área de trabalho do monitor principal: sem a barra superior e o dock do GNOME."""
    display = Gdk.Display.get_default()
    return (display.get_primary_monitor() or display.get_monitor(0)).get_workarea()


class _TopWindow(Gtk.Window):
    """Janela X11 sem decoração, sem foco, fixa acima das outras em todas as áreas."""

    def __init__(self) -> None:
        global _css_done
        super().__init__(title="Maverick", decorated=False, resizable=False, accept_focus=False,
                         skip_taskbar_hint=True, skip_pager_hint=True, type_hint=Gdk.WindowTypeHint.DOCK)
        self.set_keep_above(True)
        self.stick()
        if not _css_done:
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                     Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            _css_done = True
        screen = self.get_screen()
        if (visual := screen.get_rgba_visual()) and screen.is_composited():
            self.set_visual(visual)  # transparência
        self.set_app_paintable(True)
        self.connect("delete-event", lambda *_: True)  # não deixa fechar


class Cover(_TopWindow):
    """Cobre a área de trabalho enquanto o site bloqueado estiver em foco. Não pega o
    foco do teclado: trocar de aba (Ctrl+Tab) ou fechar (Ctrl+W) continua funcionando."""

    def __init__(self) -> None:
        super().__init__()
        self.set_app_paintable(False)  # o GTK pinta o fundo da classe .cover
        self.get_style_context().add_class("cover")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.title, self.text = Gtk.Label(), Gtk.Label(justify=Gtk.Justification.CENTER)
        hint = Gtk.Label(label="Troque de aba (Ctrl+Tab) ou feche a aba (Ctrl+W) para continuar.")
        for label, css in ((self.title, "cover-title"), (self.text, "cover-text"), (hint, "cover-hint")):
            label.get_style_context().add_class(css)
            box.pack_start(label, False, False, 0)
        self.add(box)

    def show_block(self, title: str, text: str) -> None:
        self.title.set_text(title)
        self.text.set_text(text)
        if not self.get_visible():
            area = _workarea()
            self.set_size_request(area.width, area.height)
            self.move(area.x, area.y)
            self.show_all()


class Overlay(_TopWindow):
    def __init__(self) -> None:
        super().__init__()
        self.label = Gtk.Label()
        self.label.get_style_context().add_class("pill")
        self.add(self.label)
        self._state = ""
        self.connect("size-allocate", lambda *_: self._place())

    def _place(self) -> None:
        area = _workarea()
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
