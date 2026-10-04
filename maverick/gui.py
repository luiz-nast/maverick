"""Janela do Maverick (GTK 4 + libadwaita): uso de hoje, limite e sites bloqueados.

Só lê o estado gravado pelo daemon e grava a config; o daemon aplica a config sem
reiniciar. O bloqueio no sistema é aplicado via pkexec + maverick-blockctl.
"""

from __future__ import annotations

import math
import subprocess

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

from . import __version__, blocking  # noqa: E402
from .store import APP_ID, APP_NAME, Config, State, fmt  # noqa: E402

REPO_URL = "https://github.com/luiz-nast/maverick"

CSS = """
.ring-time { font-size: 46px; font-weight: 800; font-feature-settings: "tnum"; }
.ring-sub  { font-size: 14px; opacity: 0.65; font-feature-settings: "tnum"; }
.status-pill { padding: 5px 14px; border-radius: 999px; font-weight: 700; font-size: 13px; }
.status-pill.idle    { background: alpha(@view_fg_color, 0.08); }
.status-pill.playing { background: alpha(@success_color, 0.18); color: @success_color; }
.status-pill.warning { background: alpha(@warning_color, 0.22); color: @warning_color; }
.status-pill.blocked { background: alpha(@error_color, 0.18); color: @error_color; }
.hero { padding: 12px 0 6px 0; }
"""

RING_COLORS = {
    "idle": "#3584e4",
    "playing": "#2ec27e",
    "warning": "#e5a50a",
    "blocked": "#e01b24",
}

STATUS_TEXT = {
    "idle": "Parado",
    "playing": "Assistindo agora",
    "warning": "Quase no limite",
    "blocked": "Tempo esgotado, volte amanhã",
}


def _rgba(spec: str, alpha: float = 1.0) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.parse(spec)
    c.alpha = alpha
    return c


class Ring(Gtk.Widget):
    """Anel de progresso desenhado com GSK (sem cairo)."""

    SIZE = 220
    WIDTH = 16

    def __init__(self) -> None:
        super().__init__()
        self.fraction = 0.0
        self.state = "idle"
        self.set_size_request(self.SIZE, self.SIZE)
        self.set_halign(Gtk.Align.CENTER)

    def update(self, fraction: float, state: str) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if fraction != self.fraction or state != self.state:
            self.fraction, self.state = fraction, state
            self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        r = min(w, h) / 2 - self.WIDTH / 2 - 2
        cx, cy = w / 2, h / 2
        stroke = Gsk.Stroke.new(self.WIDTH)
        stroke.set_line_cap(Gsk.LineCap.ROUND)

        track = Gsk.PathBuilder.new()
        track.add_circle(Graphene.Point().init(cx, cy), r)
        snapshot.append_stroke(track.to_path(), stroke, _rgba(self._fg(), 0.10))

        if self.fraction <= 0:
            return
        color = _rgba(RING_COLORS[self.state])
        if self.fraction >= 0.999:
            full = Gsk.PathBuilder.new()
            full.add_circle(Graphene.Point().init(cx, cy), r)
            snapshot.append_stroke(full.to_path(), stroke, color)
            return
        a0 = -math.pi / 2
        a1 = a0 + 2 * math.pi * self.fraction
        x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
        x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
        large = 1 if self.fraction > 0.5 else 0
        path = Gsk.Path.parse(f"M {x0:.3f} {y0:.3f} A {r:.3f} {r:.3f} 0 {large} 1 {x1:.3f} {y1:.3f}")
        snapshot.append_stroke(path, stroke, color)

    def _fg(self) -> str:
        c = self.get_color()
        return f"rgb({int(c.red * 255)},{int(c.green * 255)},{int(c.blue * 255)})"


class Window(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=APP_NAME, default_width=460, default_height=820)
        self.config = Config.load()
        self._last_seconds: int | None = None
        self._playing_until = 0
        self._top_cache: list = []
        self._site_rows: list[Gtk.Widget] = []
        self._top_rows: list[Gtk.Widget] = []
        self._block_status = blocking.status()

        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gio.Menu()
        menu.append("Sobre o Maverick", "app.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        view.add_top_bar(header)

        page = Adw.PreferencesPage()
        page.add(self._build_hero())
        page.add(self._build_youtube_group())
        page.add(self._build_today_group())
        page.add(self._build_sites_group())
        view.set_content(page)
        self.toasts.set_child(view)
        self.set_content(self.toasts)

        self.refresh_usage()
        self.refresh_service()
        self.rebuild_sites()
        GLib.timeout_add_seconds(1, self.refresh_usage)
        GLib.timeout_add_seconds(5, self.refresh_slow)

    # --- construção --------------------------------------------------------
    def _build_hero(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, css_classes=["hero"])
        self.ring = Ring()
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.time_label = Gtk.Label(css_classes=["ring-time"])
        self.sub_label = Gtk.Label(css_classes=["ring-sub"])
        center.append(self.time_label)
        center.append(self.sub_label)
        overlay = Gtk.Overlay(halign=Gtk.Align.CENTER)
        overlay.set_child(self.ring)
        overlay.add_overlay(center)
        self.status_pill = Gtk.Label(halign=Gtk.Align.CENTER, css_classes=["status-pill", "idle"])
        box.append(overlay)
        box.append(self.status_pill)
        group.add(box)
        return group

    def _build_youtube_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="YouTube",
            description="Conta só enquanto um vídeo está tocando. Zera à meia-noite.",
        )
        self.limit_row = Adw.SpinRow.new_with_range(5, 240, 5)
        self.limit_row.set_title("Limite diário")
        self.limit_row.set_subtitle("minutos por dia")
        self.limit_row.set_value(self.config.limit_minutes)
        self.limit_row.connect("notify::value", self._on_limit_changed)
        group.add(self.limit_row)

        self.service_row = Adw.ActionRow(title="Contador em segundo plano")
        self.service_icon = Gtk.Image()
        self.service_row.add_prefix(self.service_icon)
        self.service_button = Gtk.Button(label="Iniciar", valign=Gtk.Align.CENTER, css_classes=["pill"])
        self.service_button.connect("clicked", self._on_start_service)
        self.service_row.add_suffix(self.service_button)
        group.add(self.service_row)
        return group

    def _build_today_group(self) -> Adw.PreferencesGroup:
        self.today_group = Adw.PreferencesGroup(title="Mais assistidos hoje")
        return self.today_group

    def _build_sites_group(self) -> Adw.PreferencesGroup:
        self.sites_group = Adw.PreferencesGroup(title="Sites de jogos bloqueados")
        self.apply_button = Gtk.Button(label="Aplicar", valign=Gtk.Align.CENTER,
                                       css_classes=["suggested-action", "pill"])
        self.apply_button.connect("clicked", self._on_apply)
        self.sites_group.set_header_suffix(self.apply_button)
        self.add_row = Adw.EntryRow(title="Adicionar site (ex.: exemplo.com)", show_apply_button=True)
        self.add_row.connect("apply", self._on_add_site)
        return self.sites_group

    # --- atualização -------------------------------------------------------
    def refresh_usage(self) -> bool:
        state = State.load()
        used = state.seconds
        limit = self.config.limit_minutes * 60
        now = GLib.get_monotonic_time() // 1_000_000
        if self._last_seconds is not None and used > self._last_seconds:
            self._playing_until = now + 2
        self._last_seconds = used

        if used >= limit:
            status = "blocked"
        elif now <= self._playing_until:
            warn = self.config.warn_minutes_left * 60
            status = "warning" if limit - used <= warn else "playing"
        else:
            status = "idle"

        self.ring.update(used / limit if limit else 1.0, status)
        self.time_label.set_text(fmt(used))
        left = max(0, limit - used)
        self.sub_label.set_text(f"de {fmt(limit)} · restam {fmt(left)}")
        self.status_pill.set_text(STATUS_TEXT[status])
        self.status_pill.set_css_classes(["status-pill", status])

        top = state.top(5)
        if top != self._top_cache:
            self._top_cache = top
            for row in self._top_rows:
                self.today_group.remove(row)
            self._top_rows = []
            if not top:
                row = Adw.ActionRow(title="Nada assistido hoje", subtitle="Os vídeos aparecem aqui conforme você assiste.")
                self._top_rows.append(row)
            for title, secs in top:
                row = Adw.ActionRow(title=GLib.markup_escape_text(title), title_lines=1)
                row.add_suffix(Gtk.Label(label=fmt(secs), css_classes=["dim-label", "numeric"]))
                self._top_rows.append(row)
            for row in self._top_rows:
                self.today_group.add(row)
        return True

    def refresh_slow(self) -> bool:
        self.refresh_service()
        st = blocking.status()
        if st.hosts != self._block_status.hosts or st.helper_installed != self._block_status.helper_installed:
            self._block_status = st
            self.rebuild_sites()
        return True

    def refresh_service(self) -> None:
        active = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", "maverick.service"]
        ).returncode == 0
        self.service_row.set_subtitle("Rodando: o tempo está sendo contado" if active
                                      else "Parado: nada está sendo contado")
        self.service_icon.set_from_icon_name("emblem-ok-symbolic" if active else "dialog-warning-symbolic")
        self.service_icon.set_css_classes(["success"] if active else ["warning"])
        self.service_button.set_visible(not active)

    def rebuild_sites(self) -> None:
        st = self._block_status
        wanted = self.config.blocked_sites
        applied = set(st.hosts)
        if not st.helper_installed:
            desc = "O bloqueio no sistema precisa do pacote .deb instalado."
        elif st.in_sync(wanted):
            desc = "Ativo no sistema: /etc/hosts e políticas do Firefox e Chrome."
        else:
            desc = "Mudanças pendentes. Clique em Aplicar (pede a senha de administrador)."
        self.sites_group.set_description(desc)
        pending = st.helper_installed and not st.in_sync(wanted)
        self.apply_button.set_sensitive(pending)
        self.apply_button.set_label("Aplicar" if pending or not st.helper_installed else "Aplicado")
        self.apply_button.set_css_classes(["suggested-action", "pill"] if pending else ["pill"])

        for row in self._site_rows:
            self.sites_group.remove(row)
        self._site_rows = []
        for name, domains in blocking.group_by_site(wanted):
            ok = all(d in applied for d in domains)
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle=", ".join(domains))
            icon = Gtk.Image.new_from_icon_name("security-high-symbolic" if ok else "content-loading-symbolic")
            icon.set_css_classes(["success"] if ok else ["dim-label"])
            icon.set_tooltip_text("Bloqueado no sistema" if ok else "Ainda não aplicado")
            row.add_prefix(icon)
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text="Remover da lista")
            remove.connect("clicked", self._on_remove_site, name, domains)
            row.add_suffix(remove)
            self._site_rows.append(row)
        self._site_rows.append(self.add_row)
        for row in self._site_rows:
            self.sites_group.add(row)

    # --- ações -------------------------------------------------------------
    def _on_limit_changed(self, row: Adw.SpinRow, _pspec) -> None:
        minutes = int(row.get_value())
        if minutes != self.config.limit_minutes:
            self.config = Config.load()
            self.config.limit_minutes = minutes
            self.config.save()
            self.refresh_usage()

    def _on_start_service(self, _btn) -> None:
        subprocess.run(["systemctl", "--user", "enable", "--now", "maverick.service"])
        self.refresh_service()

    def _on_add_site(self, row: Adw.EntryRow) -> None:
        domain = blocking.normalize_domain(row.get_text())
        if not domain:
            self.toasts.add_toast(Adw.Toast(title="Endereço inválido. Use algo como exemplo.com"))
            return
        self.config = Config.load()
        if domain in self.config.blocked_sites:
            self.toasts.add_toast(Adw.Toast(title=f"{domain} já está na lista"))
        else:
            self.config.blocked_sites.append(domain)
            self.config.save()
            self.toasts.add_toast(Adw.Toast(title=f"{domain} adicionado. Clique em Aplicar."))
        row.set_text("")
        self.rebuild_sites()

    def _on_remove_site(self, _btn, name: str, domains: list[str]) -> None:
        dialog = Adw.AlertDialog(
            heading=f"Desbloquear {name}?",
            body="Você colocou esse site aqui por um motivo. Tem certeza?",
        )
        dialog.add_response("cancel", "Manter bloqueado")
        dialog.add_response("remove", "Desbloquear")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d, response: str) -> None:
            if response != "remove":
                return
            self.config = Config.load()
            self.config.blocked_sites = [d for d in self.config.blocked_sites if d not in domains]
            self.config.save()
            self.rebuild_sites()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_apply(self, _btn) -> None:
        if not blocking.HELPER.exists():
            self.toasts.add_toast(Adw.Toast(title="Instale o pacote .deb para bloquear sites"))
            return
        domains = Config.load().blocked_sites
        argv = ["pkexec", str(blocking.HELPER), *(["apply", *domains] if domains else ["clear"])]
        self.apply_button.set_sensitive(False)
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDERR_PIPE | Gio.SubprocessFlags.STDOUT_SILENCE)

        def done(p: Gio.Subprocess, res) -> None:
            _ok, _out, err = p.communicate_utf8_finish(res)
            code = p.get_exit_status()
            if code == 0:
                msg = "Bloqueio aplicado. Reinicie o Firefox para a página de bloqueio dele."
            elif code in (126, 127):
                msg = "Autenticação cancelada"
            else:
                msg = f"Falha ao aplicar: {(err or '').strip()[:80]}"
            self.toasts.add_toast(Adw.Toast(title=msg, timeout=5))
            self._block_status = blocking.status()
            self.rebuild_sites()

        proc.communicate_utf8_async(None, None, done)


class MaverickApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        GLib.set_application_name(APP_NAME)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self) -> None:
        win = self.get_active_window() or Window(self)
        win.present()
        # Sem foco inicial: senão o campo de limite abre selecionado.
        GLib.idle_add(lambda: win.set_focus(None) or False)

    def _on_about(self, *_args) -> None:
        about = Adw.AboutDialog(
            application_name=APP_NAME,
            application_icon=APP_ID,
            version=__version__,
            developer_name="Luiz Felipe Nast",
            website=REPO_URL,
            issue_url=f"{REPO_URL}/issues",
            license_type=Gtk.License.MIT_X11,
            comments="Limite diário de YouTube que conta só o tempo com vídeo tocando, "
                     "e bloqueio de sites de jogos no sistema.",
        )
        about.present(self.get_active_window())


def run_gui() -> int:
    GLib.set_prgname("maverick")
    return MaverickApp().run([])
