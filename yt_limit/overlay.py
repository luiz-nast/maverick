"""Janelas GTK: o contador flutuante no canto da tela e a tela de bloqueio."""

from __future__ import annotations

import os

# No GNOME Wayland, janelas nativas não podem pedir "sempre no topo".
# Via XWayland o Mutter respeita _NET_WM_STATE_ABOVE, então forçamos X11.
os.environ.setdefault("GDK_BACKEND", "x11")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from .store import fmt  # noqa: E402

CSS = b"""
.pill {
  background-color: rgba(20, 20, 20, 0.88);
  color: #ffffff;
  border-radius: 14px;
  padding: 6px 14px;
  font-family: monospace;
  font-size: 15px;
  font-weight: bold;
}
.pill.idle    { color: #bdbdbd; }
.pill.playing { color: #7CFC9A; }
.pill.warning { color: #FFD166; }
.pill.blocked { color: #FF6B6B; }

.block-bg {
  background-color: rgba(10, 10, 10, 0.96);
  color: #ffffff;
}
.block-title { font-size: 42px; font-weight: bold; color: #FF6B6B; }
.block-text  { font-size: 20px; color: #dddddd; }
.block-small { font-size: 14px; color: #888888; }
"""


def _install_css() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


class Overlay(Gtk.Window):
    """Pílula no canto superior direito: `▶ 12:34 / 30:00`."""

    MARGIN = 12

    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        _install_css()
        self.set_title("yt-limit")
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.DOCK)
        self.stick()

        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None and screen.is_composited():
            self.set_visual(visual)
        self.set_app_paintable(True)

        self.label = Gtk.Label(label="")
        self.label.get_style_context().add_class("pill")
        self.add(self.label)
        self._state_class = ""
        self.connect("size-allocate", lambda *_: self._place())
        self.connect("delete-event", lambda *_: True)  # não deixa fechar

    def _place(self) -> None:
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        # A área de trabalho desconta a barra superior e o dock do GNOME;
        # a geometria crua colocaria a pílula atrás da barra.
        area = monitor.get_workarea()
        width, _ = self.get_size()
        self.move(area.x + area.width - width - self.MARGIN, area.y + self.MARGIN)

    def update(self, used: int, limit: int, state: str) -> None:
        icon = {"playing": "▶", "warning": "▶", "blocked": "⛔", "idle": "⏸"}[state]
        self.label.set_text(f"{icon} {fmt(used)} / {fmt(limit)}")
        ctx = self.label.get_style_context()
        if self._state_class:
            ctx.remove_class(self._state_class)
        ctx.add_class(state)
        self._state_class = state
        if not self.get_visible():
            self.show_all()
        self._place()


class BlockScreen(Gtk.Window):
    """Tela cheia semi-opaca mostrada ao atingir o limite. Some ao pressionar Esc,
    mas volta a aparecer se um vídeo do YouTube voltar a tocar."""

    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        self.set_title("yt-limit — limite atingido")
        self.set_decorated(False)
        self.set_keep_above(True)
        self.set_skip_taskbar_hint(True)
        self.stick()
        self.get_style_context().add_class("block-bg")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Chega de YouTube por hoje")
        title.get_style_context().add_class("block-title")
        self.text = Gtk.Label(label="")
        self.text.get_style_context().add_class("block-text")
        self.text.set_justify(Gtk.Justification.CENTER)
        hint = Gtk.Label(label="Esc fecha este aviso. O vídeo continua pausado até amanhã.")
        hint.get_style_context().add_class("block-small")
        for w in (title, self.text, hint):
            box.pack_start(w, False, False, 0)
        self.add(box)

        self.connect("delete-event", lambda *_: True)
        self.connect("key-press-event", self._on_key)
        self.dismissed = False

    def _on_key(self, _w, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.dismissed = True
            self.hide()
        return True

    def show_blocked(self, used: int, limit: int, until_reset: str) -> None:
        self.text.set_text(
            f"Você usou {fmt(used)} dos {fmt(limit)} de hoje.\n"
            f"O contador zera em {until_reset}."
        )
        if not self.get_visible():
            self.dismissed = False
            self.fullscreen()
            self.show_all()
            self.present()
