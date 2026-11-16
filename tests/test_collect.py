"""~/.local/share/homelab-bot-venv/bin/python -m unittest discover -s tests -v"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import collect  # noqa: E402

GOOD = {"time": 0, "host": "fedora", "cpu": 10, "temp": 45.0, "ram": (50, 8e9, 16e9), "swap": (10, 1e9, 8e9),
        "load": (0.5, 0.5, 0.5), "uptime": 3600, "disks": {"/": (30, 60e9, 200e9), "/mnt/storage": (1, 1e9, 1e12)},
        "containers": {"homepage": ("running", "Up 2h")}, "kuma": {"Homepage": 1},
        "tailscale": {"state": "Running", "peers": {"pixel": True}}, "backup": ("2026-11-10", 3600),
        "units": {"homelab-backup.service": "ok"}, "speed": ("933 Mbps", "107 Mbps", 11.6), "heartbeat_age": 60}


def bad(**kw):
    return {**GOOD, **kw}


class Problems(unittest.TestCase):
    def test_all_good(self):
        self.assertEqual(collect.problems(GOOD), {})

    def test_each_problem(self):
        cases = {
            "ram": bad(ram=(95, 15e9, 16e9)),
            "disk:/": bad(disks={"/": (95, 1, 2), "/mnt/storage": (1, 1, 2)}),
            "disk:/mnt/storage": bad(disks={"/": (30, 1, 2), "/mnt/storage": None}),
            "container:homepage": bad(containers={"homepage": ("exited", "Exited (1)")}),
            "docker": bad(containers=None),
            "kuma:Homepage": bad(kuma={"Homepage": 0}),
            "kuma": bad(kuma=None),
            "tailscale": bad(tailscale={"state": "Stopped", "peers": {}}),
            "backup": bad(backup=("old", 30 * 3600)),
            "unit:homelab-backup.service": bad(units={"homelab-backup.service": "failed"}),
            "ps3": bad(ps3={"cpu": 60, "rsx": 82, "fan": 50}),
            "tv_ssh": bad(tv_ssh=True),
            "ps3_hen": bad(ps3_nohen=3),
            "radio": bad(radio_down=5),
            "psn": bad(psn_error="401"),
            "user:vice-tv.service": bad(user_units={"vice-tv.service": False}),
            "user:syncthing.service": bad(user_units={"syncthing.service": False}),
            "container:whisper": bad(containers={"whisper": ("running", "Up 3 hours (unhealthy)")}),
            "unit:homelab-scrub.service": bad(units={"homelab-scrub.service": "failed"}),
            "speed": bad(speed_slow=("120 Mbps", "20 Mbps")),
            "update_snapshot": bad(update_snapshot="failed 2026-11-14 05:00: btrfs snapshot of / failed"),
            "sata": bad(sata_errors=(1, "22:02", "ata5")),
            "ci:homelab": bad(ci_failed={"homelab": ["compose"]}),
            "expiry:PSN login (npsso)": bad(time=1e9, expiries={"PSN login (npsso)": (1e9 + 3 * 86400, "Renew it")}),
        }
        for key, snap in cases.items():
            self.assertIn(key, collect.problems(snap), key)

    def test_expiry_far_off_or_expired(self):
        far = {"x": (1e9 + 30 * 86400, "")}
        self.assertNotIn("expiry:x", collect.problems(bad(time=1e9, expiries=far)))
        gone = collect.problems(bad(time=1e9, expiries={"x": (1e9 - 86400, "Renew")}))
        self.assertTrue(gone["expiry:x"].startswith("x expired on "), gone)

    def test_kuma_quiet_just_after_boot(self):
        self.assertNotIn("kuma", collect.problems(bad(kuma=None, uptime=60)))
        self.assertNotIn("kuma:Homepage", collect.problems(bad(kuma={"Homepage": 0}, uptime=60)))
        self.assertIn("kuma", collect.problems(bad(kuma=None, uptime=collect.BOOT_GRACE)))

    def test_heat_needs_three_readings(self):
        hot = bad(temp=90.0)
        self.assertNotIn("temp", collect.problems(hot, hot_count=1))
        self.assertIn("temp", collect.problems(hot, hot_count=2))

    def test_status_card_render(self):
        d = collect.status_parts(GOOD, {})
        self.assertEqual(d["colour"], "green")
        self.assertIn("All quiet", d["title"])
        self.assertEqual(d["alert"], "")
        self.assertEqual([h for h, _ in d["sections"]], ["PC", "Homelab"])  # no consoles in GOOD: no Now playing
        pc = d["sections"][0][1]
        self.assertTrue(pc.startswith("**CPU** 10%"))  # no light while it's fine
        self.assertIn("1/1 running", d["sections"][1][1])
        self.assertNotIn("homepage", d["sections"][1][1])  # only what isn't fine is listed
        self.assertLess(sum(len(t) for _, t in d["sections"]) + len(d["sub"]), 3500)  # a card holds 4000 characters
        bad_ = collect.status_parts(bad(kuma={"Homepage": 0}), collect.problems(bad(kuma={"Homepage": 0})))
        self.assertEqual(bad_["colour"], "red")
        self.assertEqual(bad_["title"], "1 problem, Shane.")
        self.assertIn("Homepage", bad_["alert"])
        self.assertIn("Homepage", bad_["sections"][1][1])

    def test_status_card_devices(self):
        d = collect.status_parts(bad(ps5="on", ps5_game="Astro Bot", ps3=None, ps3_up=False, streaming=False,
                                     tv={"power": "on", "app": "YouTube", "playing": "Lofi"}), {})
        now = dict(d["sections"])["Now playing"]
        self.assertIn("**PS5** · Astro Bot", now)
        self.assertIn("**TV** · YouTube · Lofi", now)
        self.assertIn("Off: Switch · Moonlight", now)  # an off PS3 is left out (unplugged since 2026-11-16)

    def test_status_card_switch(self):
        d = collect.status_parts(bad(ps5="off", ps3=None, ps3_up=False, nsw=True, streaming=False,
                                     tv={"power": "on", "app": "Switch (HDMI 2)", "playing": None}), {})
        self.assertIn("**Switch** · on · on the TV", dict(d["sections"])["Now playing"])

    def test_ps3_cool_or_off_is_fine(self):
        self.assertNotIn("ps3", collect.problems(bad(ps3={"cpu": 55, "rsx": 72, "fan": 30})))
        self.assertNotIn("ps3", collect.problems(bad(ps3=None)))

    def test_restart_notice(self):
        d = collect.status_parts(bad(restart="updates are downloaded"), {})
        self.assertIn("Restart needed", d["alert"])
        self.assertEqual(d["colour"], "green")  # a pending restart isn't a problem

if __name__ == "__main__":
    unittest.main()
