import datetime
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import playtime  # noqa: E402


class Playtime(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        playtime.FILE = os.path.join(self.dir.name, "playtime.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_week_sums_games_and_days(self):
        d = datetime.date(2026, 11, 13)
        for _ in range(3):
            playtime.add_minute("GTA VI", d)
        playtime.add_minute("Astro Bot", d - datetime.timedelta(days=2))
        playtime.add_minute("Old", d - datetime.timedelta(days=8))
        games, days = playtime.week(d)
        self.assertEqual(games, {"GTA VI": 3, "Astro Bot": 1})
        self.assertEqual(days["2026-11-13"], 3)
        self.assertEqual(len(days), 7)

    def test_fmt(self):
        self.assertEqual(playtime.fmt(5), "5 min")
        self.assertEqual(playtime.fmt(125), "2 h 05 min")
