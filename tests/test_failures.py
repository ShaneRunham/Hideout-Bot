"""What happens when things the bot depends on are down (overhaul pass 2, 2026-11-16)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import discord  # noqa: E402

import collect  # noqa: E402
import radio  # noqa: E402
import status  # noqa: E402


class Skip(unittest.TestCase):
    def test_vice_tv_down_means_the_tv_isnt_listening(self):
        with mock.patch.object(radio.urllib.request, "urlopen", side_effect=OSError("refused")):
            self.assertFalse(radio.tv_listening())
            self.assertTrue(radio.may_skip(5, 1))  # the Crew may skip

    def test_tv_listening_blocks_the_crew_not_shane(self):
        with mock.patch.object(radio, "tv_listening", return_value=True):
            self.assertFalse(radio.may_skip(5, 1))
            self.assertTrue(radio.may_skip(1, 1))


class HealRadio(unittest.TestCase):
    def test_restart_after_two_minutes_problem_after_five(self):
        b = status.StatusMixin()
        b.post = mock.AsyncMock()
        snap = {"containers": {"radio": ("running", "Up")}, "radio_stream": False}
        with mock.patch.object(status, "run", mock.AsyncMock(return_value=(0, ""))) as run:
            for minute in range(1, 6):
                s = dict(snap)
                asyncio.run(b.heal_radio(s))
                if minute == 1:
                    run.assert_not_awaited()
                if minute == 2:
                    run.assert_awaited_once()  # restarted once...
            self.assertEqual(run.await_count, 1)  # ...and not again within 10 minutes
        self.assertIn("radio", collect.problems({**PROBLEM_BASE, "radio_down": s["radio_down"]}))

    def test_back_resets(self):
        b = status.StatusMixin()
        b.radio_down = 4
        asyncio.run(b.heal_radio({"containers": {"radio": ("running", "Up")}, "radio_stream": True}))
        self.assertEqual(b.radio_down, 0)


PROBLEM_BASE = {"time": 0, "host": "fedora", "cpu": 10, "temp": 45.0, "ram": (50, 8e9, 16e9),
                "swap": (10, 1e9, 8e9), "load": (0.5, 0.5, 0.5), "uptime": 3600, "disks": {"/": (30, 60e9, 200e9)},
                "containers": {}, "kuma": {}, "tailscale": {"state": "Running", "peers": {}},
                "backup": ("x", 3600), "units": {}, "heartbeat_age": 60}


class DiscordTrouble(unittest.TestCase):
    def test_a_deleted_game_card_still_ends_the_session(self):
        b = status.StatusMixin()
        b.state = {"ps5_sessions": {"Sam": {"game": "Minecraft", "start": 0, "channel": 5, "msg": 9,
                                               "cover": None, "missing": 2}}}
        gone = mock.Mock(edit=mock.AsyncMock(side_effect=discord.NotFound(mock.Mock(status=404), "gone")))
        b.guild = mock.Mock(get_channel=mock.Mock(return_value=mock.Mock(get_partial_message=lambda _: gone)))
        with mock.patch.object(status, "save_state"):
            asyncio.run(b.game_session("Sam", None))
        self.assertNotIn("Sam", b.state["ps5_sessions"])

    def test_ha_down_whos_on_raises_and_the_tick_catches_it(self):
        b = status.StatusMixin()
        b.state, b.emoji = {}, {}
        with mock.patch.object(status.gaming, "psn_friends", side_effect=OSError("HA down")):
            with self.assertRaises(OSError):
                asyncio.run(b.whos_on())
        # tick() wraps whos_on in try/except after the HA export (see test_review_fixes.TickOrder for the order)


if __name__ == "__main__":
    unittest.main()
