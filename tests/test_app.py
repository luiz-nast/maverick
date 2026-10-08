import os
import time
import unittest

from maverick import app as appmod
from maverick.mpris import Player

appmod.notify = lambda *a, **k: None


class FakeMpris:
    def __init__(self):
        self.status = "Paused"
        self.url = "https://www.youtube.com/watch?v=1"
        self.paused = []

    def players(self):
        return [
            Player("org.mpris.MediaPlayer2.firefox.instance_1", self.status, "Video", self.url, ""),
            Player("org.mpris.MediaPlayer2.firefox.instance_2", "Playing", "Pin", "https://br.pinterest.com/pin/1/", ""),
        ]

    def pause(self, p):
        self.paused.append(p.bus_name)


class StubOverlay:
    def __init__(self):
        self.visible, self.last = False, None

    def update(self, used, limit, state):
        self.visible, self.last = True, state

    def show_message(self, text, state):
        self.visible, self.last = True, text

    def hide(self):
        self.visible = False


class StubCover:
    def __init__(self):
        self.visible, self.title = False, None

    def show_block(self, title, text):
        self.visible, self.title = True, title

    def hide(self):
        self.visible = False


class FakeA11y:
    def __init__(self, verdict=None, url=None):
        self.verdict, self.url = verdict, url

    def private_media_is_youtube(self):
        return self.verdict

    def focused_url(self):
        return self.url


class DaemonTest(unittest.TestCase):
    def make(self, limit=1):
        a = appmod.App(show_overlay=False)
        a.mpris, a.overlay, a.cover, a.a11y = FakeMpris(), StubOverlay(), StubCover(), FakeA11y()
        a.idle_seconds = lambda: 0.0
        a.state.sites = {}
        a.config.limit_minutes, a.config.hide_after_seconds = limit, 2
        a.state.seconds, a.state.per_video = 0, {}
        a._state_mtime = appmod.mtime(appmod.STATE_FILE)
        return a

    def test_counts_only_playing_youtube(self):
        a = self.make(limit=30)
        for _ in range(5):
            a.tick()
        self.assertEqual(a.state.seconds, 0)
        self.assertFalse(a.overlay.visible)
        a.mpris.status = "Playing"
        for _ in range(10):
            a.tick()
        self.assertEqual(a.state.seconds, 10)
        self.assertTrue(a.overlay.visible)

    def test_overlay_hides_after_delay(self):
        a = self.make(limit=30)
        a.mpris.status = "Playing"
        a.tick()
        a.mpris.status = "Paused"
        a.tick()
        self.assertTrue(a.overlay.visible)
        a._visible_until = time.monotonic() - 0.1
        a.tick()
        self.assertFalse(a.overlay.visible)

    def test_limit_pauses_and_shows_notice(self):
        a = self.make(limit=1)
        a.mpris.status = "Playing"
        for _ in range(61):
            a.tick()
        self.assertEqual(a.state.seconds, 60)
        self.assertIn("org.mpris.MediaPlayer2.firefox.instance_1", a.mpris.paused)
        self.assertNotIn("org.mpris.MediaPlayer2.firefox.instance_2", a.mpris.paused)
        self.assertEqual(a.overlay.last, appmod.TIME_UP)

    def test_private_window_layers(self):
        a = self.make()
        priv = Player("org.mpris.MediaPlayer2.firefox.instance_9", "Playing", "O Firefox está reproduzindo mídia", "", "")
        spotify = Player("org.mpris.MediaPlayer2.spotify", "Playing", "x", "", "")
        a.a11y = FakeA11y(None)
        a.config.count_private_media = True
        self.assertTrue(a.is_youtube(priv))
        self.assertFalse(a.is_youtube(spotify))
        a.config.count_private_media = False
        self.assertFalse(a.is_youtube(priv))
        a.a11y = FakeA11y(True)
        self.assertTrue(a.is_youtube(priv))
        a.a11y = FakeA11y(False)
        a.config.count_private_media = True
        self.assertFalse(a.is_youtube(priv))

    def test_external_reset_is_not_overwritten(self):
        a = self.make(limit=30)
        a.mpris.status = "Playing"
        for _ in range(5):
            a.tick()
        self.assertEqual(a.state.seconds, 5)
        st = appmod.State.load()
        st.seconds, st.per_video = 0, {}
        st.save()
        os.utime(appmod.STATE_FILE, (time.time() + 5, time.time() + 5))
        a.tick()
        self.assertEqual(a.state.seconds, 1)
        self.assertEqual(appmod.State.load().seconds, 1)

    def test_instagram_daily_counts_only_when_focused_and_present(self):
        a = self.make(limit=30)
        a.config.sites["instagram.com"]["minutes"] = 1
        a.a11y.url = "https://www.instagram.com/reels/"
        for _ in range(10):
            a.tick()
        self.assertEqual(a.state.sites["instagram.com"]["seconds"], 10)
        self.assertTrue(a.overlay.visible)
        a.idle_seconds = lambda: 600.0  # saiu do computador, sem mídia
        a.tick()
        self.assertEqual(a.state.sites["instagram.com"]["seconds"], 10)
        a.idle_seconds = lambda: 0.0
        a.a11y.url = "https://github.com/"  # outra aba em foco
        a.tick()
        self.assertEqual(a.state.sites["instagram.com"]["seconds"], 10)
        a.a11y.url = "https://www.instagram.com/"
        for _ in range(60):
            a.tick()
        self.assertEqual(a.state.sites["instagram.com"]["seconds"], 60)
        self.assertTrue(a.cover.visible)
        self.assertEqual(a.cover.title, "Instagram bloqueado")
        a.a11y.url = "https://github.com/"
        a.tick()
        self.assertFalse(a.cover.visible)

    def test_pinterest_cycle(self):
        a = self.make(limit=30)
        a.config.sites["pinterest.com"].update(allow_minutes=1, block_minutes=2)
        a.a11y.url = "https://br.pinterest.com/pin/1/"
        for _ in range(60):
            a.tick()
        st = a.state.sites["pinterest.com"]
        self.assertTrue(a.cover.visible)
        self.assertAlmostEqual(st["blocked_until"] - time.time(), 120, delta=2)
        a.tick()
        self.assertEqual(st["round_used"], 60)  # bloqueado: não conta
        st["blocked_until"] = time.time() - 1  # a pausa acabou
        a.tick()
        self.assertFalse(a.cover.visible)
        self.assertEqual((st["round_used"], st["blocked_until"]), (1, 0))

    def test_config_hot_reload(self):
        a = self.make(limit=30)
        cfg = appmod.Config.load()
        cfg.limit_minutes = 45
        cfg.save()
        os.utime(appmod.CONFIG_FILE, (time.time() + 5, time.time() + 5))
        a.tick()
        self.assertEqual(a.config.limit_minutes, 45)


if __name__ == "__main__":
    unittest.main()
