"""The PS5 now-playing card in the Crew's channels (status.StatusMixin.ps5_post)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import status  # noqa: E402


class FakeBot(status.StatusMixin):
    def __init__(self):
        self.state = {}
        self.sent, self.edited = [], []
        msg = mock.Mock(id=42)
        self.chan = mock.Mock(id=7, send=mock.AsyncMock(side_effect=lambda **kw: self.sent.append(kw) or msg))
        partial = mock.Mock(edit=mock.AsyncMock(side_effect=lambda **kw: self.edited.append(kw)), delete=mock.AsyncMock())
        self.chan.get_partial_message = mock.Mock(return_value=partial)
        self.guild = mock.Mock(get_channel=mock.Mock(return_value=self.chan))
        self.asked = []
        self.emoji = None

    def ch(self, key):
        self.asked.append(key)
        return self.chan


def tick(b, game):
    with mock.patch.object(status, "save_state"):
        asyncio.run(b.ps5_post({"ps5_game": game}))


class PS5Post(unittest.TestCase):
    def test_start_blip_stop(self):
        b = FakeBot()
        tick(b, "Minecraft")
        self.assertEqual(b.asked, ["minecraft"])  # Minecraft goes to #minecraft
        self.assertEqual(len(b.sent), 1)
        tick(b, "Minecraft")
        tick(b, None)  # a minute without the game: not over yet
        tick(b, "Minecraft")  # back: still the same session, no new post
        self.assertEqual((len(b.sent), len(b.edited)), (1, 0))
        for _ in range(3):
            tick(b, None)
        self.assertEqual(len(b.edited), 1)  # ended: the card says how long
        self.assertNotIn("Shane", b.state["ps5_sessions"])

    def test_switching_games(self):
        b = FakeBot()
        tick(b, "Minecraft")
        tick(b, "Call of Duty®")
        self.assertEqual((len(b.sent), len(b.edited)), (2, 1))
        self.assertEqual(b.asked, ["minecraft", "ps5"])
        self.assertEqual(b.state["ps5_sessions"]["Shane"]["game"], "Call of Duty®")


class SwitchPost(unittest.TestCase):
    def run_switch(self, b, friends):
        with mock.patch.object(status, "save_state"), mock.patch.object(status.gaming, "switch_friends", return_value=friends), \
                mock.patch.object(status, "save_cover"), mock.patch.dict(status.SWITCH_NAMES, {"Didi": "Sam"}):
            asyncio.run(b.switch_games())

    def test_switch_card_kept_apart_from_psn(self):
        b = FakeBot()
        with mock.patch.object(status, "save_state"):
            asyncio.run(b.game_session("Sam", "Call of Duty®"))  # her PSN card
        self.run_switch(b, [{"name": "Didi", "game": "Minecraft", "art": "https://x/icon.jpg", "status": "online", "last": None}])
        self.assertEqual(b.asked, ["ps5", "online", "minecraft"])  # #online (waits for the PSN part), then the game card
        self.assertIn("Sam is playing", str(b.sent[1]["view"].to_components()))
        self.assertEqual(b.state["online_switch"].count("**Sam** · playing **Minecraft**"), 1)
        self.assertEqual(set(b.state["ps5_sessions"]), {"Sam", "Sam (Switch)"})

    def test_nintendo_down_keeps_the_session(self):
        b = FakeBot()
        self.run_switch(b, [{"name": "Didi", "game": "Minecraft", "art": None, "status": "online", "last": None}])
        for _ in range(4):
            self.run_switch(b, None)  # not logged in / no answer: nothing ends
        self.assertEqual(len(b.edited), 0)  # neither card touched
        self.assertIn("Sam (Switch)", b.state["ps5_sessions"])

    def test_old_switch_card_is_removed(self):
        b = FakeBot()
        b.state.update(online_psn="PSN lines", switch_online_card=99, switch_online_text="old")
        self.run_switch(b, [])
        b.chan.get_partial_message.assert_any_call(99)
        self.assertNotIn("switch_online_card", b.state)
        self.assertEqual(len(b.sent), 1)  # the one combined card

    def test_other_switch_games_go_to_switch_games(self):
        b = FakeBot()
        self.run_switch(b, [{"name": "Didi", "game": "Mario Kart 8 Deluxe", "art": None, "status": "online", "last": None}])
        self.assertEqual(b.asked, ["online", "switch"])

    def test_switch_online_lines(self):
        b = FakeBot()
        b.state["online_psn"] = "PSN lines"  # one card: the PlayStation part, then the Switch part
        self.run_switch(b, [{"name": "Didi", "game": None, "art": None, "status": "offline", "last": 1763300000},
                            {"name": "Shane", "game": None, "art": None, "status": "idle", "last": None}])
        text = str(b.sent[0]["view"].to_components())
        self.assertLess(text.index("PLAYSTATION"), text.index("SWITCH"))
        self.assertLess(text.index("**Shane** · idle"), text.index("**Sam** · offline · last on <t:1763300000:R>"))
        self.run_switch(b, [{"name": "Didi", "game": None, "art": None, "status": "offline", "last": 1763300000},
                            {"name": "Shane", "game": None, "art": None, "status": "idle", "last": None}])
        self.assertEqual((len(b.sent), len(b.edited)), (1, 0))  # unchanged: not edited again


class GTA6Cover(unittest.TestCase):
    def test_launch_art_ready(self):
        """Rockstar's art is in place for launch day (2026-11-19), whatever PSN calls the game. Reads the repo's
        copy, not ~/homelab (CI runs elsewhere)."""
        covers = os.path.join(os.path.dirname(__file__), "..", "..", "home-assistant/config/www/vice-panel/covers")
        self.enterContext(mock.patch.object(status, "PS5_COVERS", covers))
        for name in ("Grand Theft Auto VI", "Grand Theft Auto VI™", "GTA VI", "Grand Theft Auto 6"):
            self.assertTrue(str(status.ps5_cover(name)).endswith("ps5-grand-theft-auto-vi.png"), name)
        for name in ("Grand Theft Auto V", "Grand Theft Auto: Vice City"):
            self.assertNotIn("grand-theft-auto-vi.png", str(status.ps5_cover(name)), name)


if __name__ == "__main__":
    unittest.main()
