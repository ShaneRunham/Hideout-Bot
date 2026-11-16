import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import remind  # noqa: E402

NOW = datetime.datetime(2026, 11, 14, 11, 0)


class Remind(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(remind.due("30m", NOW), NOW + datetime.timedelta(minutes=30))
        self.assertEqual(remind.due("2h", NOW), NOW + datetime.timedelta(hours=2))
        self.assertEqual(remind.due("1h30m", NOW), NOW + datetime.timedelta(minutes=90))
        self.assertEqual(remind.due("1h 30min", NOW), NOW + datetime.timedelta(minutes=90))

    def test_clock_today_and_tomorrow(self):
        self.assertEqual(remind.due("18:00", NOW), datetime.datetime(2026, 11, 14, 18, 0))
        self.assertEqual(remind.due("9.15", NOW), datetime.datetime(2026, 11, 15, 9, 15))
        self.assertEqual(remind.due("11:00", NOW), datetime.datetime(2026, 11, 15, 11, 0))

    def test_rejects(self):
        for bad in ("", "soon", "0m", "25:00", "12:60", "9999h", "m"):
            self.assertIsNone(remind.due(bad, NOW), bad)

    def test_say_when(self):
        self.assertEqual(remind.say_when(datetime.datetime(2026, 11, 14, 18, 0), NOW), "at 18:00")
        self.assertEqual(remind.say_when(datetime.datetime(2026, 11, 15, 9, 0), NOW), "tomorrow at 09:00")
        self.assertEqual(remind.say_when(datetime.datetime(2026, 11, 17, 9, 0), NOW), "on Tue at 09:00")


if __name__ == "__main__":
    unittest.main()
