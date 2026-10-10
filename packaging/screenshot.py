"""Gera docs/screenshot.png: abre a janela com dados de exemplo e salva um PNG.

    GDK_BACKEND=wayland python3 packaging/screenshot.py docs/screenshot.png [dark] [expand]
"""

import json
import os
import sys
import tempfile
import time
import types
from datetime import date
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["XDG_CONFIG_HOME"], os.environ["XDG_DATA_HOME"] = f"{tmp}/c", f"{tmp}/d"
Path(f"{tmp}/d/maverick").mkdir(parents=True)
Path(f"{tmp}/d/maverick/state.json").write_text(json.dumps({
    "day": date.today().isoformat(), "seconds": 1134,
    "per_video": {"Como funciona um motor a jato": 512, "Top Gun: Maverick – cena do treino": 341,
                  "Receita de pão de fermentação natural": 198, "Lo-fi para estudar": 83},
    "sites": {"instagram.com": {"seconds": 192, "round_used": 192, "round_allow": 300, "blocked_until": 0},
              "pinterest.com": {"seconds": 300, "round_used": 300, "round_allow": 300,
                                "blocked_until": time.time() + 612}}}))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gio, GLib, Graphene, Gtk  # noqa: E402

from maverick import blocking, gui  # noqa: E402

gui.blocking.status = lambda: blocking.BlockStatus(True, blocking.default_domains())
gui.subprocess.run = lambda *a, **k: types.SimpleNamespace(returncode=0)
out = sys.argv[1] if len(sys.argv) > 1 else "docs/screenshot.png"


class App(gui.MaverickApp):
    def do_activate(self):
        Adw.StyleManager.get_default().set_color_scheme(
            Adw.ColorScheme.FORCE_DARK if "dark" in sys.argv else Adw.ColorScheme.FORCE_LIGHT)
        win = gui.Window(self)
        win.set_default_size(460, 1200)
        win.present()
        GLib.idle_add(lambda: win.set_focus(None) or False)
        win._playing_until = GLib.get_monotonic_time() // 1_000_000 + 60
        win.refresh_usage()
        if "expand" in sys.argv:
            for row in win._focus_rows.values():
                row.set_expanded(True)

        def shot():
            w, h = win.get_width(), win.get_height()
            snap = Gtk.Snapshot()
            Gtk.WidgetPaintable.new(win).snapshot(snap, w, h)
            win.get_renderer().render_texture(snap.to_node(), Graphene.Rect().init(0, 0, w, h)).save_to_png(out)
            print("salvo:", out)
            self.quit()
            return False

        GLib.timeout_add(1500, shot)


app = App()
app.set_flags(app.get_flags() | Gio.ApplicationFlags.NON_UNIQUE)
app.run([])
