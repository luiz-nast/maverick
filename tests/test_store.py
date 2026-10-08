import io
import unittest
from contextlib import redirect_stdout

from maverick import store
from maverick.__main__ import main
from maverick.store import Config, State, usage_status


class LimitRuleTest(unittest.TestCase):
    def test_raise_waits_until_tomorrow(self):
        c = Config(limit_minutes=30)
        self.assertFalse(c.set_limit(60, "2026-10-05"))
        self.assertEqual(c.effective_limit("2026-10-05"), 30)
        self.assertEqual(c.effective_limit("2026-10-06"), 60)

    def test_lower_applies_now_and_sticks_today(self):
        c = Config(limit_minutes=30)
        self.assertTrue(c.set_limit(20, "2026-10-05"))
        self.assertFalse(c.set_limit(30, "2026-10-05"))
        self.assertEqual(c.effective_limit("2026-10-05"), 20)
        self.assertEqual(c.effective_limit("2026-10-06"), 30)

    def test_raise_then_lower_below_today(self):
        c = Config(limit_minutes=30)
        c.set_limit(90, "2026-10-05")
        self.assertTrue(c.set_limit(25, "2026-10-05"))
        self.assertEqual(c.effective_limit("2026-10-05"), 25)
        self.assertEqual(c.effective_limit("2026-10-06"), 25)


class SiteRuleTest(unittest.TestCase):
    def test_site_for_url(self):
        from maverick.sites import site_for_url
        rules = Config().sites
        self.assertEqual(site_for_url("https://br.pinterest.com/pin/1/", rules), "pinterest.com")
        self.assertEqual(site_for_url("https://www.instagram.com/reels/", rules), "instagram.com")
        self.assertIsNone(site_for_url("https://notinstagram.com/", rules))
        self.assertIsNone(site_for_url(None, rules))

    def test_daily_site_limit_follows_youtube_rule(self):
        c = Config()
        self.assertFalse(c.set_site_minutes("instagram.com", 60, "2026-10-08"))
        self.assertEqual(c.site_limit("instagram.com", "2026-10-08"), 30)
        self.assertEqual(c.site_limit("instagram.com", "2026-10-09"), 60)
        self.assertTrue(c.set_site_minutes("instagram.com", 10, "2026-10-08"))
        self.assertEqual(c.site_limit("instagram.com", "2026-10-08"), 10)

    def test_cycle_change_applies_next_round(self):
        from maverick.sites import evaluate
        c, st = Config(), {}
        evaluate(c, "pinterest.com", st, 1000.0, count=True)
        c.sites["pinterest.com"]["allow_minutes"] = 30
        self.assertEqual(evaluate(c, "pinterest.com", st, 1001.0, count=False).limit, 300)

    def test_day_roll_keeps_cycle(self):
        s = State(day="1999-01-01", sites={"pinterest.com": {"seconds": 50, "blocked_until": 9e12}})
        s.roll_day()
        self.assertEqual(s.sites["pinterest.com"], {"seconds": 0, "blocked_until": 9e12})


class StatusTest(unittest.TestCase):
    def test_usage_status(self):
        self.assertEqual(usage_status(10, 600, False, 5), "idle")
        self.assertEqual(usage_status(10, 600, True, 5), "playing")
        self.assertEqual(usage_status(400, 600, True, 5), "warning")
        self.assertEqual(usage_status(600, 600, False, 5), "blocked")


class FilesTest(unittest.TestCase):
    def test_config_roundtrip_normalizes_sites(self):
        Config(limit_minutes=40, blocked_sites=["https://www.Poki.com/x", "bad domain", "poki.com"]).save()
        c = Config.load()
        self.assertEqual((c.limit_minutes, c.blocked_sites), (40, ["poki.com"]))

    def test_corrupt_files_fall_back_to_defaults(self):
        store.CONFIG_FILE.write_text("[1, 2]")
        store.STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        store.STATE_FILE.write_text('{"day": "1999-01-01", "seconds": 99, "per_video": null}')
        self.assertEqual(Config.load().limit_minutes, 30)
        s = State.load()
        self.assertEqual((s.day, s.seconds, s.per_video), (store.today_iso(), 0, {}))

    def test_cli_reset_and_limit(self):
        s = State.load()
        s.add_second("x")
        s.save()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(["reset"]), 0)
            self.assertEqual(main(["limit", "15"]), 0)
        self.assertEqual(State.load().seconds, 0)
        self.assertEqual(Config.load().effective_limit(), 15)


if __name__ == "__main__":
    unittest.main()
