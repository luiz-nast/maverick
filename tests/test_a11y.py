import unittest
from unittest import mock

from gi.repository import GLib

from maverick import a11y as a11y_mod
from maverick.a11y import Tab, Window, is_private_window, private_media_verdict, selected_title

YT = "Rick Astley - Never Gonna Give You Up - YouTube"
VIMEO = "The New Vimeo Player | Vídeos e Filmes no Vimeo"
PRIV = " — Mozilla Firefox — navegação privativa"


def win(selected, tabs, private=True):
    return Window(f"{selected}{PRIV}" if private else f"{selected} — Mozilla Firefox", private, tabs)


class TitleTest(unittest.TestCase):
    def test_private_marker(self):
        self.assertTrue(is_private_window("X" + PRIV))
        self.assertTrue(is_private_window("X — Mozilla Firefox Private Browsing"))
        self.assertFalse(is_private_window("About YouTube - YouTube — Mozilla Firefox"))

    def test_selected_title(self):
        self.assertEqual(selected_title(YT + PRIV), YT)
        self.assertEqual(selected_title("Mozilla Firefox — navegação privativa"), "")
        self.assertEqual(selected_title("Inbox - Google Chrome"), "Inbox")


class VerdictTest(unittest.TestCase):
    def test_selected_youtube_counts(self):
        self.assertTrue(private_media_verdict([win(YT, [])]))
        self.assertFalse(private_media_verdict([win(VIMEO, [])]))

    def test_fresh_tab_list_audio_decides(self):
        tabs = [Tab(YT, False, "playing"), Tab(VIMEO, True, None)]
        self.assertTrue(private_media_verdict([win(VIMEO, tabs)]))
        tabs = [Tab(YT, True, None), Tab(VIMEO, False, "playing")]
        self.assertFalse(private_media_verdict([win(YT, tabs)]))

    def test_blocked_audio_is_not_playing(self):
        tabs = [Tab(YT, False, "blocked"), Tab(VIMEO, True, None)]
        self.assertFalse(private_media_verdict([win(VIMEO, tabs)]))

    def test_stale_tab_list_is_ignored(self):
        # Lista parada mostra um YouTube tocando, mas a janela já está em outro site.
        stale = [Tab(YT, True, "playing")]
        w = win(VIMEO, stale)
        self.assertFalse(w.tabs_fresh)
        self.assertFalse(private_media_verdict([w]))

    def test_normal_window_youtube_does_not_leak_into_private(self):
        windows = [win(YT, [], private=False), win(VIMEO, [])]
        self.assertFalse(private_media_verdict(windows))

    def test_no_private_window_uses_all(self):
        self.assertTrue(private_media_verdict([win(YT, [], private=False)]))
        self.assertFalse(private_media_verdict([]))


class MediaTitleTest(unittest.TestCase):
    def check(self, windows, title):
        a = a11y_mod.A11y()
        with mock.patch.object(a, "windows", return_value=windows):
            return a.media_is_youtube(title)

    def test_chrome_titles(self):
        yt = Window("AI Killed The Best Job of the 21st Century - YouTube - Google Chrome", False, [])
        other = Window("Instagram - Google Chrome", False, [])
        self.assertEqual(self.check([other, yt], "AI Killed The Best Job of the 21st Century"), (True, True))
        playing = Window("AI Killed The Best Job of the 21st Century - YouTube - Reprodução de áudio - Google Chrome",
                         False, [])
        self.assertEqual(self.check([playing], "AI Killed The Best Job of the 21st Century"), (True, True))
        self.assertFalse(a11y_mod.looks_like_youtube("Como ganhar dinheiro - YouTube tips"))
        vimeo = Window("Curta incrível on Vimeo - Google Chrome", False, [])
        self.assertEqual(self.check([vimeo], "Curta incrível"), (False, True))
        self.assertEqual(self.check([other], "Sem janela com esse título"), (False, False))
        self.assertEqual(self.check(None, "x"), (None, False))


class StuckActiveWindowTest(unittest.TestCase):
    """Chrome preso como ACTIVE não pode esconder o Firefox que recebeu o foco depois."""

    def test_most_recently_activated_window_wins(self):
        a = a11y_mod.A11y()
        a.conn = object()
        chrome, firefox = (":1.9", "/chrome"), (":1.5", "/firefox")
        titles = {chrome: "Vagas - Google Chrome", firefox: "Instagram — Mozilla Firefox"}
        active = {chrome: True, firefox: False}
        apps = [("Google Chrome", ":1.9", "/app"), ("Firefox", ":1.5", "/app")]
        with mock.patch.object(a, "shell_focus", return_value=None), \
             mock.patch.object(a, "_browser_apps", return_value=apps), \
             mock.patch.object(a, "_children", side_effect=lambda b, p: [chrome] if b == ":1.9" else [firefox]), \
             mock.patch.object(a, "_role", return_value="frame"), \
             mock.patch.object(a, "_states", side_effect=lambda *f: int(active[f]) << a11y_mod.STATE_ACTIVE), \
             mock.patch.object(a, "_name", side_effect=lambda *f: titles[f]), \
             mock.patch.object(a, "_url_for", return_value=None):
            self.assertEqual(a.focused_tab()[0], "Vagas")
            active[firefox] = True  # foco foi para o Firefox; o Chrome continua "ativo"
            self.assertEqual(a.focused_tab()[0], "Instagram")
            active[firefox] = False  # saiu do Firefox
            self.assertEqual(a.focused_tab()[0], "Vagas")


class ShellFocusTest(unittest.TestCase):
    """Com a extensão do GNOME, o foco real manda; o ACTIVE preso do Chrome não conta."""

    def setUp(self):
        self.a = a11y_mod.A11y()
        self.a.conn = object()
        self.chrome, self.firefox = (":1.9", "/chrome"), (":1.5", "/firefox")
        self.titles = {self.chrome: "(2) Pinterest - Google Chrome", self.firefox: "Vagas — Mozilla Firefox"}
        self.active = {self.chrome: True, self.firefox: False}  # Chrome preso como ativo
        self.a._pids = {":1.9": 900, ":1.5": 500}

    def focused(self, focus):
        a = self.a
        apps = [("Google Chrome", ":1.9", "/app"), ("Firefox", ":1.5", "/app")]
        with mock.patch.object(a, "shell_focus", return_value=focus), \
             mock.patch.object(a, "_browser_apps", return_value=apps), \
             mock.patch.object(a, "_children", side_effect=lambda b, p: [self.chrome] if b == ":1.9" else [self.firefox]), \
             mock.patch.object(a, "_role", return_value="frame"), \
             mock.patch.object(a, "_states", side_effect=lambda *f: int(self.active[f]) << a11y_mod.STATE_ACTIVE), \
             mock.patch.object(a, "_name", side_effect=lambda *f: self.titles[f]), \
             mock.patch.object(a, "_url_for", return_value=None):
            tab = a.focused_tab()
        return tab and tab[0]

    def test_other_app_focused_counts_nothing(self):
        self.assertIsNone(self.focused((4242, "Claude")))

    def test_focused_browser_wins_over_stuck_chrome(self):
        self.assertEqual(self.focused((500, "Vagas — Mozilla Firefox")), "Vagas")

    def test_focused_chrome(self):
        self.assertEqual(self.focused((900, "(2) Pinterest - Google Chrome")), "(2) Pinterest")

    def test_chrome_audio_marker_still_matches(self):
        self.titles[self.chrome] = "Stories • Instagram - Reprodução de áudio - Google Chrome"
        self.active[self.chrome] = False  # Chrome sem ACTIVE nenhum (visto depois do login)
        self.assertEqual(self.focused((900, "Stories • Instagram - Google Chrome")),
                         "Stories • Instagram - Reprodução de áudio")

    def test_title_mismatch_falls_back_to_active(self):
        self.assertEqual(self.focused((900, "Pinterest - Google Chrome")), "(2) Pinterest")

    def test_title_mismatch_with_two_active_counts_nothing(self):
        self.chrome2 = (":1.9", "/chrome2")
        self.titles[self.chrome2] = "Imprimir"
        self.active[self.chrome2] = True
        a = self.a
        apps = [("Google Chrome", ":1.9", "/app")]
        with mock.patch.object(a, "shell_focus", return_value=(900, "Salvar como")), \
             mock.patch.object(a, "_browser_apps", return_value=apps), \
             mock.patch.object(a, "_children", return_value=[self.chrome, self.chrome2]), \
             mock.patch.object(a, "_role", return_value="frame"), \
             mock.patch.object(a, "_states", side_effect=lambda *f: int(self.active[f]) << a11y_mod.STATE_ACTIVE), \
             mock.patch.object(a, "_name", side_effect=lambda *f: self.titles[f]), \
             mock.patch.object(a, "_url_for", return_value=None):
            self.assertIsNone(a.focused_tab())

    def test_without_extension_keeps_old_rule(self):
        self.assertEqual(self.focused(None), "(2) Pinterest")


class FocusedTabCacheTest(unittest.TestCase):
    """Documento guardado que deixou de existir não pode travar a detecção."""

    def test_dead_cached_document_is_replaced(self):
        a = a11y_mod.A11y()
        a.conn = object()
        frame, dead, live = (":1.5", "/frame"), (":1.5", "/doc/old"), (":1.5", "/doc/new")
        a._docs[frame] = dead
        names = {"/frame": "Instagram — Mozilla Firefox", "/doc/new": "Instagram"}

        def name(bus, path):
            if path == dead[1]:
                raise GLib.Error("UnknownObject")
            return names[path]

        with mock.patch.object(a, "shell_focus", return_value=None), \
             mock.patch.object(a, "_browser_apps", return_value=[("Firefox", ":1.5", "/app")]), \
             mock.patch.object(a, "_children", return_value=[frame]), \
             mock.patch.object(a, "_role", return_value="frame"), \
             mock.patch.object(a, "_states", return_value=1 << a11y_mod.STATE_ACTIVE), \
             mock.patch.object(a, "_name", side_effect=name), \
             mock.patch.object(a, "_find_doc", return_value=live), \
             mock.patch.object(a11y_mod.dbus, "call", return_value=("https://www.instagram.com/",)):
            self.assertEqual(a.focused_tab(), ("Instagram", "https://www.instagram.com/"))
        self.assertEqual(a._docs[frame], live)


if __name__ == "__main__":
    unittest.main()
