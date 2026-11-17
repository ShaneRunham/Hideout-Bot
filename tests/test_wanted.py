import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wanted  # noqa: E402

T = 1_800_000_000.0


class Wanted(unittest.TestCase):
    def test_weights(self):
        self.assertEqual(wanted.weight("disk:/mnt/storage"), 3)
        self.assertEqual(wanted.weight("container:radio"), 2)
        self.assertEqual(wanted.weight("kuma"), 2)
        self.assertEqual(wanted.weight("kuma:Jellyfin"), 2)
        self.assertEqual(wanted.weight("speed"), 1)
        self.assertEqual(wanted.weight("expiry:PSN", "PSN expires in 5 days (20 Nov). Renew"), 1)
        self.assertEqual(wanted.weight("expiry:PSN", "PSN expired on 10 Nov. Renew"), 3)

    def test_clean(self):
        st = wanted.update({}, {}, T)
        self.assertEqual((st["stars"], st["change"], st["evading"]), (0, None, 0))
        self.assertEqual(st["clean_since"], T)

    def test_up_heat_and_crowd(self):
        st = wanted.update({}, {"speed": "Internet is slow"}, T)
        self.assertEqual((st["stars"], st["change"]), (1, "up"))
        st = wanted.update(st, {"speed": "Internet is slow"}, T + 3600)  # an hour unfixed: +1
        self.assertEqual((st["stars"], st["change"]), (2, "up"))
        st = wanted.update(st, {"speed": "x", "ram": "y", "container:a": "Container `a` is exited (Exited (1))"}, T + 3660)
        self.assertEqual(st["stars"], 3)  # worst is 2 (speed with heat, or the container), +1 for three problems
        self.assertEqual(st["crimes"][0]["key"], "speed")  # same stars: the oldest first
        self.assertEqual(st["crimes"][1]["what"], "Container a is exited")

    def test_no_heat(self):
        st = wanted.update({"since": {"tv_ssh": T - 99999}}, {"tv_ssh": "The TV's SSH server is on"}, T)
        self.assertEqual(st["stars"], 1)  # on for a day: still one star

    def test_cap(self):
        probs = {"disk:/": "full", "sata": "x", "backup": "y"}
        st = wanted.update({"since": {k: T - 99999 for k in probs}}, probs, T)
        self.assertEqual(st["stars"], 5)

    def test_evade_and_caught_again(self):
        st = wanted.update({}, {"container:a": "down"}, T)
        st = wanted.update(st, {}, T + 60)
        self.assertEqual((st["stars"], st["change"], st["evading"]), (0, "evading", 2))
        self.assertEqual(st["fixed"], ["down"])
        st = wanted.update(st, {}, T + 120)
        self.assertEqual((st["evading"], st["change"]), (2, None))  # still flashing (EVADE 110 s)
        st = wanted.update(st, {}, T + 200)
        self.assertEqual((st["evading"], st["change"], st["evaded"]), (0, "clear", 2))
        self.assertEqual(st["clean_since"], T + 200)
        st = wanted.update(st, {}, T + 260)
        self.assertIsNone(st["change"])

    def test_flap_is_quiet(self):
        st = wanted.update({}, {"container:a": "down"}, T)
        st = wanted.update(st, {}, T + 60)
        st = wanted.update(st, {"container:a": "down"}, T + 90)  # back while evading: same level, no alert
        self.assertEqual((st["stars"], st["evading"], st["change"]), (2, 0, None))
        self.assertNotIn("lost", st)
        st = wanted.update(st, {}, T + 150)
        st = wanted.update(st, {"disk:/": "full"}, T + 180)  # worse while evading: that's news
        self.assertEqual((st["stars"], st["change"]), (3, "up"))

    def test_streak(self):
        st = wanted.update({}, {}, T)
        st = wanted.update(st, {"speed": "x"}, T + 5000)
        self.assertEqual(st["best_clean"], 5000)
        st = wanted.update(st, {}, T + 6000)
        st = wanted.update(st, {}, T + 6200)
        self.assertEqual(st["clean_since"], T + 6200)  # from "Lost them", not from the drop
        st = wanted.update(st, {"speed": "x"}, T + 9200)
        self.assertEqual(st["best_clean"], 5000)  # 3000 s is not a record

    def test_history_and_days(self):
        st = wanted.update({}, {}, T)
        st = wanted.update(st, {"speed": "x"}, T + 100)
        st = wanted.update(st, {"speed": "x"}, T + 160)  # no change: no new history row
        st = wanted.update(st, {}, T + 400)
        st = wanted.update(st, {}, T + 600)  # "clear" (lost them) adds a row at the same level
        self.assertEqual([h[1] for h in st["history"]], [0, 1, 0, 0])
        self.assertEqual(wanted.day_peaks(st["history"], [(T, T + 1000), (T + 1000, T + 2000)]), [(1, 300.0), (0, 0.0)])
        self.assertEqual(wanted.day_peaks([[T - 50, 2]], [(T, T + 10)]), [(2, 10.0)])  # carried in from before

    def test_for_ha(self):
        st = wanted.update({}, {"speed": "Internet is slow. The last test got 3 down"}, T)
        out = wanted.for_ha(st)
        self.assertEqual(out["stars"], 1)
        self.assertEqual(out["crimes"], [{"key": "speed", "what": "Internet is slow", "stars": 1, "since": T}])


if __name__ == "__main__":
    unittest.main()
