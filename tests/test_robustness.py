"""Robustez: programas que não respondem não podem travar o contador, a pílula nem o bloqueio."""

import threading
import time
import unittest
from unittest import mock

from gi.repository import GLib

from maverick import a11y as a11y_mod
from maverick import app as appmod
from maverick import dbus as dbus_mod
from maverick import mpris as mpris_mod
from maverick.mpris import Mpris
from maverick.sites import SiteStatus
from maverick.store import State

from .test_app import FakeA11y, FakeMpris, StubCover, StubOverlay

appmod.notify = lambda *a, **k: None


class StrikesTest(unittest.TestCase):
    def test_quarantine_after_three_in_a_row_reset_on_success(self):
        s = dbus_mod.Strikes(seconds=60, limit=3)
        s.fail("x"); s.fail("x")
        self.assertFalse(s.blocked("x"))
        s.ok("x"); s.fail("x"); s.fail("x")
        self.assertFalse(s.blocked("x"))  # o sucesso no meio zerou a contagem
        s.fail("x")
        self.assertTrue(s.blocked("x"))

    def test_quarantine_expires(self):
        s = dbus_mod.Strikes(seconds=0.05, limit=1)
        s.fail("x")
        self.assertTrue(s.blocked("x"))
        time.sleep(0.06)
        self.assertFalse(s.blocked("x"))


class MprisTest(unittest.TestCase):
    def make(self, hang):
        m = Mpris.__new__(Mpris)
        m.bus, m.strikes = object(), dbus_mod.Strikes()
        calls = []

        def fake_call(bus, dest, path, iface, method, args=None, reply=None, timeout=1000):
            if method == "ListNames":
                return (["org.mpris.MediaPlayer2.chromium.hung", "org.mpris.MediaPlayer2.firefox.real"],)
            calls.append((dest, timeout))
            if hang(dest):
                raise GLib.Error("Timeout was reached")
            return ({"PlaybackStatus": "Playing", "Metadata": {}},)

        return m, calls, fake_call

    def test_hung_player_quarantined_after_three_failures(self):
        m, calls, fake = self.make(lambda d: d.endswith("hung"))
        with mock.patch.object(mpris_mod.dbus, "call", side_effect=fake):
            for _ in range(6):
                self.assertEqual([p.bus_name for p in m.players()], ["org.mpris.MediaPlayer2.firefox.real"])
        self.assertEqual(sum(d.endswith("hung") for d, _ in calls), 3)
        self.assertTrue(all(t <= 300 for _, t in calls))

    def test_real_browser_survives_a_single_slow_reply(self):
        slow = {"n": 0}

        def hang(dest):
            if dest.endswith("real"):
                slow["n"] += 1
                return slow["n"] == 1  # só a 1ª consulta demora
            return False

        m, _, fake = self.make(hang)
        with mock.patch.object(mpris_mod.dbus, "call", side_effect=fake):
            seen = [len([p for p in m.players() if p.bus_name.endswith("real")]) for _ in range(4)]
        self.assertEqual(seen, [0, 1, 1, 1])


class A11yTest(unittest.TestCase):
    def test_hung_app_sidelined_only_after_repeated_failures(self):
        a = a11y_mod.A11y()
        a.conn = object()
        apps = [(":1.7", "/root/hung"), (":1.8", "/root/ff")]
        tries = []

        def name(bus, path):
            tries.append(bus)
            if bus == ":1.7":
                raise GLib.Error("Timeout was reached")
            return "Firefox"

        with mock.patch.object(a, "_connect", return_value=a.conn), \
             mock.patch.object(a, "_children", return_value=apps), \
             mock.patch.object(a, "_name", side_effect=name), \
             mock.patch.object(a11y_mod.dbus, "call", return_value=(12345,)):
            for _ in range(6):
                self.assertEqual(a.browsers_on_bus(), ["Firefox"])
        self.assertEqual(tries.count(":1.7"), 3)

    def test_tree_search_has_a_time_cap(self):
        a = a11y_mod.A11y()
        a.conn = object()

        def slow_role(b, p):
            time.sleep(0.05)
            return "panel"

        with mock.patch.object(a, "_role", side_effect=slow_role), \
             mock.patch.object(a, "_children", return_value=[(":1.8", "/x")] * 3):
            started = time.monotonic()
            self.assertIsNone(a._find_doc((":1.8", "/frame"), "Instagram"))
        self.assertLess(time.monotonic() - started, a11y_mod.SEARCH_SECONDS + 0.2)


class RenderTest(unittest.TestCase):
    def make(self):
        a = appmod.App(show_overlay=False)
        a.mpris, a.overlay, a.cover, a.a11y = FakeMpris(), StubOverlay(), StubCover(), FakeA11y()
        a.idle_seconds = lambda: 0.0
        a.state.seconds, a.state.per_video, a.state.sites = 0, {}, {}
        a._state_mtime = appmod.mtime(appmod.STATE_FILE)
        return a

    def test_blocked_site_cover_stays_when_worker_stalls(self):
        a = self.make()
        blocked = SiteStatus("Instagram", True, 180, 180, 600)
        a._snapshot = appmod.Snapshot(time.monotonic() - 30, False, "idle", 0, 1500, blocked)
        a._render()
        self.assertTrue(a.cover.visible)

    def test_pill_hides_after_last_playing_snapshot(self):
        a = self.make()
        a._snapshot = appmod.Snapshot(time.monotonic(), True, "playing", 10, 1500, None)
        a._render()
        self.assertTrue(a.overlay.visible)
        a._snapshot = appmod.Snapshot(time.monotonic() - 5, True, "playing", 10, 1500, None)
        a._visible_until = 0
        a._render()  # último retrato tocando é de 5 s atrás: passou dos 2 s
        self.assertFalse(a.overlay.visible)

    def test_worker_never_touches_gtk_and_publishes_via_idle_add(self):
        a = self.make()
        a.mpris.status = "Playing"
        a._threaded = True
        a.overlay = mock.Mock(side_effect=AssertionError)
        a.overlay.configure_mock(**{"show_message.side_effect": AssertionError("GTK fora da linha principal"),
                                    "hide.side_effect": AssertionError("GTK fora da linha principal")})
        with mock.patch.object(appmod.GLib, "idle_add") as idle:
            a.tick()
        idle.assert_called_once_with(a._render)

    def test_worker_survives_a_failing_cycle(self):
        a = self.make()
        n = {"ticks": 0}

        def flaky():
            n["ticks"] += 1
            if n["ticks"] == 1:
                raise RuntimeError("ciclo ruim")

        a.tick = flaky
        t = threading.Thread(target=a._work, daemon=True)
        t.start()
        time.sleep(1.3)
        a._stop.set()
        t.join(2)
        self.assertGreaterEqual(n["ticks"], 2)


class SaveRaceTest(unittest.TestCase):
    def test_concurrent_saves_do_not_fail(self):
        errors = []

        def loop():
            s = State.load()
            for _ in range(200):
                try:
                    s.save()
                except OSError as e:
                    errors.append(e)

        threads = [threading.Thread(target=loop) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        State.load()  # arquivo final legível


if __name__ == "__main__":
    unittest.main()
