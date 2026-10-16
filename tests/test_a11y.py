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

        with mock.patch.object(a, "_browser_apps", return_value=[("Firefox", ":1.5", "/app")]), \
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
