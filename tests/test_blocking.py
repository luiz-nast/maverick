import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maverick import blocking as b
from maverick import blockctl

HOSTS = "127.0.0.1 localhost\n::1 ip6-localhost\n"


class NormalizeTest(unittest.TestCase):
    def test_accepts_urls_and_prefixes(self):
        self.assertEqual(b.normalize_domain("https://www.Poki.com/pt/g/x?y=1"), "poki.com")
        self.assertEqual(b.normalize_domain("m.friv.com"), "friv.com")
        self.assertEqual(b.normalize_domain("clickjogos.com.br."), "clickjogos.com.br")
        self.assertEqual(b.normalize_domain("user@y8.com:443"), "y8.com")

    def test_rejects_garbage_and_injection(self):
        for bad in ["", "localhost", "poki", "a b.com", "x.com\n0.0.0.0 google.com", "-x.com", "*.poki.com", "1.2.3.4"]:
            self.assertIsNone(b.normalize_domain(bad), bad)

    def test_defaults_are_valid_and_unique(self):
        d = b.default_domains()
        self.assertEqual(len(b.DEFAULT_SITES), 10)
        self.assertEqual(len(d), len(set(d)))
        self.assertTrue(all(b.normalize_domain(x) == x for x in d))


class HostsTest(unittest.TestCase):
    def test_render_parse_roundtrip(self):
        out = b.render_hosts(HOSTS, ["poki.com", "friv.com"])
        self.assertTrue(out.startswith(HOSTS))
        self.assertIn("0.0.0.0 www.poki.com", out)
        self.assertIn(":: m.friv.com", out)
        self.assertEqual(b.hosts_domains(out), ["poki.com", "friv.com"])

    def test_reapply_replaces_block(self):
        once = b.render_hosts(HOSTS, ["poki.com"])
        twice = b.render_hosts(once, ["friv.com"])
        self.assertEqual(twice.count(b.BEGIN), 1)
        self.assertNotIn("poki.com", twice)
        self.assertEqual(b.hosts_domains(twice), ["friv.com"])

    def test_clear_restores_original(self):
        self.assertEqual(b.render_hosts(b.render_hosts(HOSTS, ["poki.com"]), []), HOSTS)

    def test_tampered_block_is_not_counted(self):
        out = b.render_hosts(HOSTS, ["poki.com", "friv.com"]).replace("0.0.0.0 friv.com\n", "")
        self.assertEqual(b.hosts_domains(out), ["poki.com"])


class FirefoxPolicyTest(unittest.TestCase):
    def test_merge_keeps_foreign_entries(self):
        existing = {"policies": {"DisableTelemetry": True, "WebsiteFilter": {"Block": ["*://evil.org/*"], "Exceptions": ["x"]}}}
        out = b.merge_firefox_policy(existing, ["poki.com"], [])
        wf = out["policies"]["WebsiteFilter"]
        self.assertEqual(wf["Block"], ["*://evil.org/*", "*://*.poki.com/*"])
        self.assertEqual(wf["Exceptions"], ["x"])
        self.assertTrue(out["policies"]["DisableTelemetry"])

    def test_merge_removes_old_patterns(self):
        existing = {"policies": {"WebsiteFilter": {"Block": ["*://*.poki.com/*", "*://*.friv.com/*"]}}}
        out = b.merge_firefox_policy(existing, ["friv.com"], ["poki.com", "friv.com"])
        self.assertEqual(out["policies"]["WebsiteFilter"]["Block"], ["*://*.friv.com/*"])
        self.assertEqual(b.merge_firefox_policy(out, [], ["friv.com"]), {"policies": {}})


class BlockctlApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "hosts").write_text(HOSTS)
        self.patches = [
            mock.patch.object(b, "HOSTS_FILE", self.tmp / "hosts"),
            mock.patch.object(b, "FIREFOX_POLICY_FILE", self.tmp / "firefox/policies/policies.json"),
            mock.patch.object(b, "CHROMIUM_POLICY_FILES", (self.tmp / "chrome/maverick.json",)),
            mock.patch.object(blockctl.subprocess, "run"),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_apply_and_clear(self):
        blockctl.apply(["poki.com", "y8.com"])
        self.assertEqual(b.hosts_domains((self.tmp / "hosts").read_text()), ["poki.com", "y8.com"])
        self.assertEqual(b.firefox_policy_domains(), {"poki.com", "y8.com"})
        self.assertEqual(json.loads((self.tmp / "chrome/maverick.json").read_text()), {"URLBlocklist": ["poki.com", "y8.com"]})
        self.assertEqual(os.stat(self.tmp / "hosts").st_mode & 0o777, 0o644)

        blockctl.apply([])
        self.assertEqual((self.tmp / "hosts").read_text(), HOSTS)
        self.assertFalse((self.tmp / "firefox/policies/policies.json").exists())
        self.assertFalse((self.tmp / "chrome/maverick.json").exists())

    def test_invalid_firefox_json_is_left_alone(self):
        f = self.tmp / "firefox/policies/policies.json"
        f.parent.mkdir(parents=True)
        f.write_text("{ broken")
        warning = blockctl.apply(["poki.com"])
        self.assertEqual(f.read_text(), "{ broken")
        self.assertIn("JSON", warning)
        self.assertEqual(b.hosts_domains((self.tmp / "hosts").read_text()), ["poki.com"])

    def test_cli_rejects_invalid_domain(self):
        with mock.patch.object(blockctl.os, "geteuid", return_value=0):
            self.assertEqual(blockctl.main(["apply", "poki.com", "bad domain"]), 2)
        self.assertEqual((self.tmp / "hosts").read_text(), HOSTS)

    def test_cli_requires_root(self):
        with mock.patch.object(blockctl.os, "geteuid", return_value=1000):
            self.assertEqual(blockctl.main(["clear"]), 1)


class StatusTest(unittest.TestCase):
    def test_sync(self):
        st = b.BlockStatus(True, ["poki.com", "y8.com"])
        self.assertTrue(st.in_sync(["y8.com", "poki.com"]))
        self.assertEqual(st.missing(["poki.com", "friv.com"]), ["friv.com"])
        self.assertEqual(st.extra(["poki.com"]), ["y8.com"])

    def test_group_by_site(self):
        self.assertEqual(b.group_by_site(["poki.com", "x.org", "poki.com.br"]),
                         [("Poki", ["poki.com", "poki.com.br"]), ("x.org", ["x.org"])])


if __name__ == "__main__":
    unittest.main()

