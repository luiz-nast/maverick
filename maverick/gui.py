"""Janela do Maverick (GTK 4 + libadwaita).

Lê o estado gravado pelo daemon e grava a config, que o daemon recarrega sozinho.
O bloqueio no sistema é aplicado via pkexec + maverick-blockctl.
"""

from __future__ import annotations

import copy
import math
import subprocess
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gsk", "4.0")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Graphene, Gsk, Gtk  # noqa: E402

from . import __version__, blocking  # noqa: E402
from .a11y import A11y  # noqa: E402
from .sites import evaluate  # noqa: E402
from .store import APP_ID, APP_NAME, Config, State, fmt, usage_status  # noqa: E402

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


def _rgba(spec: str) -> Gdk.RGBA:
    color = Gdk.RGBA()
    color.parse(spec)
    return color


RING_COLORS = {k: _rgba(v) for k, v in
               {"idle": "#3584e4", "playing": "#2ec27e", "warning": "#e5a50a", "blocked": "#e01b24"}.items()}
STATUS_TEXT = {"idle": "Parado", "playing": "Assistindo agora", "warning": "Quase no limite",
               "blocked": "Tempo esgotado, volte amanhã"}
# (subtítulo, ícone, classe) da linha "Janela anônima"
PRIVATE_STATES = {
    "exact": ("Detecção exata: separa YouTube de outros sites pelo título da aba", "emblem-ok-symbolic", "success"),
    "restart": ("Feche e abra o Firefox para ativar a detecção exata", "view-refresh-symbolic", "warning"),
    "off": ("Aproximada: ative para separar YouTube de outros sites", "dialog-warning-symbolic", "warning"),
}


class Ring(Gtk.Widget):
    """Anel de progresso desenhado com GSK (sem cairo)."""

    SIZE, WIDTH = 220, 16

    def __init__(self) -> None:
        super().__init__(halign=Gtk.Align.CENTER, width_request=self.SIZE, height_request=self.SIZE)
        self.fraction, self.state = 0.0, "idle"

    def update(self, fraction: float, state: str) -> None:
        fraction = max(0.0, min(1.0, fraction))
        if (fraction, state) != (self.fraction, self.state):
            self.fraction, self.state = fraction, state
            self.queue_draw()

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        w, h = self.get_width(), self.get_height()
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - self.WIDTH / 2 - 2
        stroke = Gsk.Stroke.new(self.WIDTH)
        stroke.set_line_cap(Gsk.LineCap.ROUND)
        circle = Gsk.PathBuilder.new()
        circle.add_circle(Graphene.Point().init(cx, cy), r)
        circle = circle.to_path()
        track = self.get_color()
        track.alpha = 0.10
        snapshot.append_stroke(circle, stroke, track)
        if self.fraction >= 0.999:
            snapshot.append_stroke(circle, stroke, RING_COLORS[self.state])
        elif self.fraction > 0:
            a = 2 * math.pi * self.fraction - math.pi / 2
            arc = (f"M {cx:.3f} {cy - r:.3f} A {r:.3f} {r:.3f} 0 {int(self.fraction > 0.5)} 1 "
                   f"{cx + r * math.cos(a):.3f} {cy + r * math.sin(a):.3f}")
            snapshot.append_stroke(Gsk.Path.parse(arc), stroke, RING_COLORS[self.state])


class Window(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=APP_NAME, default_width=460, default_height=820)
        self.config = Config.load()
        self._last_seconds: int | None = None
        self._playing_until = 0
        self._top: list | None = None
        self._top_rows: list[Gtk.Widget] = []
        self._site_rows: list[Gtk.Widget] = []
        self._block_status = blocking.status()
        self._a11y = A11y()
        self._iface = Gio.Settings.new("org.gnome.desktop.interface")
        self._timers: dict = {}
        self._focus_rows: dict[str, Adw.PreferencesRow] = {}

        page = Adw.PreferencesPage()
        for group in (self._build_hero(), self._build_youtube(), self._build_focus_sites(),
                      self._build_today(), self._build_sites()):
            page.add(group)
        menu = Gio.Menu()
        menu.append("Sobre o Maverick", "app.about")
        header = Adw.HeaderBar()
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        view = Adw.ToolbarView(content=page)
        view.add_top_bar(header)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

        self.refresh_usage()
        self.refresh_slow(force=True)
        GLib.timeout_add_seconds(1, self.refresh_usage)
        GLib.timeout_add_seconds(5, self.refresh_slow)

    # --- auxiliares ----------------------------------------------------------
    def _toast(self, title: str, timeout: int = 3) -> None:
        self.toasts.add_toast(Adw.Toast(title=title, timeout=timeout))

    def _edit_config(self, change):
        """Relê a config do disco, aplica `change` e grava (não perde mudanças da CLI)."""
        self.config = Config.load()
        result = change(self.config)
        self.config.save()
        return result

    @staticmethod
    def _replace_rows(group: Adw.PreferencesGroup, old: list, new: list) -> list:
        for row in old:
            group.remove(row)
        for row in new:
            group.add(row)
        return new

    @staticmethod
    def _set_icon(icon: Gtk.Image, name: str, css: str) -> None:
        icon.set_from_icon_name(name)
        icon.set_css_classes([css])

    def _debounce(self, key, fn) -> None:
        """Grava 1,5 s depois do último clique: passar por um valor menor no caminho
        não pode baixar o limite de hoje sem querer."""
        if key in self._timers:
            GLib.source_remove(self._timers.pop(key))

        def fire() -> bool:
            self._timers.pop(key, None)
            fn()
            return False

        self._timers[key] = GLib.timeout_add(1500, fire)

    def _spin(self, title: str, low: int, high: int, step: int, value: int, commit) -> Adw.SpinRow:
        row = Adw.SpinRow.new_with_range(low, high, step)
        row.set_title(title)
        row.set_value(value)
        row.connect("notify::value", lambda r, _p: self._debounce(r, lambda: commit(int(r.get_value()))))
        return row

    @staticmethod
    def _action_row(title: str, button_label: str, on_click) -> tuple[Adw.ActionRow, Gtk.Image, Gtk.Button]:
        row, icon = Adw.ActionRow(title=title), Gtk.Image()
        button = Gtk.Button(label=button_label, valign=Gtk.Align.CENTER, css_classes=["pill"])
        button.connect("clicked", on_click)
        row.add_prefix(icon)
        row.add_suffix(button)
        return row, icon, button

    # --- construção ----------------------------------------------------------
    def _build_hero(self) -> Adw.PreferencesGroup:
        self.ring = Ring()
        self.time_label = Gtk.Label(css_classes=["ring-time"])
        self.sub_label = Gtk.Label(css_classes=["ring-sub"])
        center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                         halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        center.append(self.time_label)
        center.append(self.sub_label)
        overlay = Gtk.Overlay(halign=Gtk.Align.CENTER, child=self.ring)
        overlay.add_overlay(center)
        self.status_pill = Gtk.Label(halign=Gtk.Align.CENTER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, css_classes=["hero"])
        box.append(overlay)
        box.append(self.status_pill)
        group = Adw.PreferencesGroup()
        group.add(box)
        return group

    def _build_youtube(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="YouTube",
                                     description="Conta só enquanto um vídeo está tocando. Zera à meia-noite.")
        self.limit_row = self._spin("Limite diário", 5, 240, 5, self.config.limit_minutes, self._commit_limit)
        self._update_limit_subtitle()
        self.service_row, self.service_icon, self.service_button = self._action_row(
            "Contador em segundo plano", "Iniciar", self._on_start_service)
        self.private_row, self.private_icon, self.private_button = self._action_row(
            "Janela anônima", "Ativar", self._on_enable_a11y)
        self.fallback_row = Adw.SwitchRow(title="Na dúvida, contar como YouTube",
                                          subtitle="Vale para vídeo anônimo enquanto a detecção não é exata",
                                          active=self.config.count_private_media)
        self.fallback_row.connect("notify::active", self._on_fallback_toggled)
        for row in (self.limit_row, self.service_row, self.private_row, self.fallback_row):
            group.add(row)
        return group

    def _build_focus_sites(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Tempo de tela por site",
            description="Conta só com o site na aba visível da janela em foco e você presente. "
                        "Usa a detecção exata (Janela anônima > Ativar).")
        for domain, rule in self.config.sites.items():
            if rule["mode"] == "daily":
                row = self._spin(rule["name"], 5, 240, 5, rule["minutes"],
                                 lambda v, d=domain: self._commit_site_minutes(d, v))
            else:
                row = Adw.ExpanderRow(title=rule["name"])
                for key, title, high in (("allow_minutes", "Tempo livre (min)", 60),
                                         ("block_minutes", "Tempo bloqueado (min)", 240)):
                    row.add_row(self._spin(title, 1, high, 1, rule[key],
                                           lambda v, d=domain, k=key: self._commit_cycle(d, k, v)))
            self._focus_rows[domain] = row
            group.add(row)
        return group

    def _build_today(self) -> Adw.PreferencesGroup:
        self.today_group = Adw.PreferencesGroup(title="Mais assistidos hoje")
        return self.today_group

    def _build_sites(self) -> Adw.PreferencesGroup:
        self.sites_group = Adw.PreferencesGroup(title="Sites de jogos bloqueados")
        self.apply_button = Gtk.Button(label="Aplicar", valign=Gtk.Align.CENTER)
        self.apply_button.connect("clicked", self._on_apply)
        self.sites_group.set_header_suffix(self.apply_button)
        self.add_row = Adw.EntryRow(title="Adicionar site (ex.: exemplo.com)", show_apply_button=True)
        self.add_row.connect("apply", self._on_add_site)
        return self.sites_group

    # --- atualização ---------------------------------------------------------
    def refresh_usage(self) -> bool:
        state = State.load()
        used, limit = state.seconds, self.config.effective_limit() * 60
        now = GLib.get_monotonic_time() // 1_000_000
        if self._last_seconds is not None and used > self._last_seconds:
            self._playing_until = now + 2  # o daemon grava a cada segundo contado
        self._last_seconds = used
        status = usage_status(used, limit, now <= self._playing_until, self.config.warn_minutes_left)
        self.ring.update(used / limit if limit else 1.0, status)
        self.time_label.set_text(fmt(used))
        self.sub_label.set_text(f"de {fmt(limit)} · restam {fmt(limit - used)}")
        self.status_pill.set_text(STATUS_TEXT[status])
        self.status_pill.set_css_classes(["status-pill", status])

        now_ts = time.time()
        for domain, row in self._focus_rows.items():
            rule = self.config.sites.get(domain)
            if not rule:
                continue
            text = evaluate(self.config, domain, copy.deepcopy(state.sites.get(domain, {})), now_ts, False).summary
            if rule["mode"] == "cycle":
                text += f" · ciclo {rule['allow_minutes']} livres / {rule['block_minutes']} bloqueado"
            elif rule["minutes"] != self.config.site_limit(domain):
                text += f" · a partir de amanhã: {rule['minutes']} min"
            row.set_subtitle(text)

        top = state.top(5)
        if top != self._top:
            self._top = top
            rows = []
            for title, secs in top:
                row = Adw.ActionRow(title=GLib.markup_escape_text(title), title_lines=1)
                row.add_suffix(Gtk.Label(label=fmt(secs), css_classes=["dim-label", "numeric"]))
                rows.append(row)
            rows = rows or [Adw.ActionRow(title="Nada assistido hoje",
                                          subtitle="Os vídeos aparecem aqui conforme você assiste.")]
            self._top_rows = self._replace_rows(self.today_group, self._top_rows, rows)
        return True

    def refresh_slow(self, force: bool = False) -> bool:
        active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", "maverick.service"]).returncode == 0
        self.service_row.set_subtitle("Rodando: o tempo está sendo contado" if active
                                      else "Parado: nada está sendo contado")
        self._set_icon(self.service_icon, *(("emblem-ok-symbolic", "success") if active
                                            else ("dialog-warning-symbolic", "warning")))
        self.service_button.set_visible(not active)

        enabled = self._iface.get_boolean("toolkit-accessibility")
        mode = "off" if not enabled else "exact" if self._a11y.browsers_on_bus() else "restart"
        subtitle, icon, css = PRIVATE_STATES[mode]
        self.private_row.set_subtitle(subtitle)
        self._set_icon(self.private_icon, icon, css)
        self.private_button.set_visible(not enabled)
        self.fallback_row.set_visible(mode != "exact")

        st = blocking.status()
        if force or st != self._block_status:
            self._block_status = st
            self.rebuild_sites()
        return True

    def rebuild_sites(self) -> None:
        st, wanted = self._block_status, self.config.blocked_sites
        pending = st.helper_installed and not st.in_sync(wanted)
        self.sites_group.set_description(
            "O bloqueio no sistema precisa do pacote .deb instalado." if not st.helper_installed else
            "Mudanças pendentes. Clique em Aplicar (pede a senha de administrador)." if pending else
            "Ativo no sistema: /etc/hosts e políticas do Firefox e Chrome.")
        self.apply_button.set_sensitive(pending)
        self.apply_button.set_label("Aplicado" if st.helper_installed and not pending else "Aplicar")
        self.apply_button.set_css_classes(["pill", "suggested-action"] if pending else ["pill"])

        rows = []
        for name, domains in blocking.group_by_site(wanted):
            ok = all(d in st.hosts for d in domains)
            row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle=", ".join(domains))
            icon = Gtk.Image(tooltip_text="Bloqueado no sistema" if ok else "Ainda não aplicado")
            self._set_icon(icon, *(("security-high-symbolic", "success") if ok
                                   else ("content-loading-symbolic", "dim-label")))
            row.add_prefix(icon)
            remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                css_classes=["flat"], tooltip_text="Remover da lista")
            remove.connect("clicked", self._on_remove_site, name, domains)
            row.add_suffix(remove)
            rows.append(row)
        self._site_rows = self._replace_rows(self.sites_group, self._site_rows, rows + [self.add_row])

    # --- ações ---------------------------------------------------------------
    def _update_limit_subtitle(self) -> None:
        today, target = self.config.effective_limit(), self.config.limit_minutes
        self.limit_row.set_subtitle(f"Hoje: {today} min · a partir de amanhã: {target} min" if target != today
                                    else "Reduzir vale na hora; aumentar só a partir de amanhã")

    def _commit_limit(self, minutes: int) -> None:
        if minutes != Config.load().limit_minutes:
            now = self._edit_config(lambda c: c.set_limit(minutes))
            self._toast(f"Limite de hoje reduzido para {minutes} min" if now else
                        f"{minutes} min a partir de amanhã. Hoje continua {self.config.effective_limit()} min.", 4)
        self._update_limit_subtitle()
        self.refresh_usage()

    def _commit_site_minutes(self, domain: str, minutes: int) -> None:
        rule = Config.load().sites.get(domain)
        if not rule or minutes == rule["minutes"]:
            return
        now = self._edit_config(lambda c: c.set_site_minutes(domain, minutes))
        self._toast(f"{rule['name']}: {minutes} min por dia, já vale hoje" if now else
                    f"{rule['name']}: {minutes} min a partir de amanhã. Hoje continua "
                    f"{self.config.site_limit(domain)} min.", 4)
        self.refresh_usage()

    def _commit_cycle(self, domain: str, key: str, minutes: int) -> None:
        rule = Config.load().sites.get(domain)
        if rule and rule[key] != minutes:
            self._edit_config(lambda c: c.sites[domain].__setitem__(key, minutes))
            self._toast(f"{rule['name']}: vale a partir da próxima rodada")
            self.refresh_usage()

    def _on_enable_a11y(self, _btn) -> None:
        self._iface.set_boolean("toolkit-accessibility", True)
        self._toast("Acessibilidade ativada. Feche e abra o Firefox.", 6)
        self.refresh_slow()

    def _on_fallback_toggled(self, row: Adw.SwitchRow, _pspec) -> None:
        self._edit_config(lambda c: setattr(c, "count_private_media", row.get_active()))

    def _on_start_service(self, _btn) -> None:
        subprocess.run(["systemctl", "--user", "enable", "--now", "maverick.service"])
        self.refresh_slow()

    def _on_add_site(self, row: Adw.EntryRow) -> None:
        domain = blocking.normalize_domain(row.get_text())
        if not domain:
            self._toast("Endereço inválido. Use algo como exemplo.com")
            return
        if domain in Config.load().blocked_sites:
            self._toast(f"{domain} já está na lista")
        else:
            self._edit_config(lambda c: c.blocked_sites.append(domain))
            self._toast(f"{domain} adicionado. Clique em Aplicar.")
        row.set_text("")
        self.rebuild_sites()

    def _on_remove_site(self, _btn, name: str, domains: list[str]) -> None:
        dialog = Adw.AlertDialog(heading=f"Desbloquear {name}?",
                                 body="Você colocou esse site aqui por um motivo. Tem certeza?")
        dialog.add_response("cancel", "Manter bloqueado")
        dialog.add_response("remove", "Desbloquear")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "remove":
                self._edit_config(lambda c: setattr(c, "blocked_sites",
                                                    [d for d in c.blocked_sites if d not in domains]))
                self.rebuild_sites()

        dialog.connect("response", on_response)
        dialog.present(self)

    def _on_apply(self, _btn) -> None:
        if not blocking.HELPER.exists():
            self._toast("Instale o pacote .deb para bloquear sites")
            return
        domains = Config.load().blocked_sites
        self.apply_button.set_sensitive(False)
        proc = Gio.Subprocess.new(["pkexec", str(blocking.HELPER), *(["apply", *domains] if domains else ["clear"])],
                                  Gio.SubprocessFlags.STDERR_PIPE | Gio.SubprocessFlags.STDOUT_SILENCE)

        def done(p: Gio.Subprocess, res) -> None:
            err = p.communicate_utf8_finish(res)[2] or ""
            code = p.get_exit_status()
            self._toast("Bloqueio aplicado. Reinicie o Firefox para a página de bloqueio dele." if code == 0 else
                        "Autenticação cancelada" if code in (126, 127) else
                        f"Falha ao aplicar: {err.strip()[:80]}", 5)
            self._block_status = blocking.status()
            self.rebuild_sites()

        proc.communicate_utf8_async(None, None, done)


class MaverickApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        GLib.set_application_name(APP_NAME)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", self._on_about)
        self.add_action(about)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self) -> None:
        win = self.get_active_window() or Window(self)
        win.present()
        GLib.idle_add(lambda: win.set_focus(None) or False)  # senão o campo de limite abre selecionado

    def _on_about(self, *_args) -> None:
        Adw.AboutDialog(
            application_name=APP_NAME, application_icon=APP_ID, version=__version__,
            developer_name="Luiz Felipe Nast", website=REPO_URL, issue_url=f"{REPO_URL}/issues",
            license_type=Gtk.License.MIT_X11,
            comments="Limite diário de YouTube que conta só o tempo com vídeo tocando, "
                     "e bloqueio de sites de jogos no sistema.",
        ).present(self.get_active_window())


def run_gui() -> int:
    GLib.set_prgname("maverick")
    return MaverickApp().run([])
