import unittest

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


if __name__ == "__main__":
    unittest.main()
