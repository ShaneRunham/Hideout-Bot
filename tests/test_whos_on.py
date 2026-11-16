"""#online card and the Crew's game cards (status.StatusMixin.whos_on -> game_session)."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import status  # noqa: E402


class FakeBot(status.StatusMixin):
    def __init__(self):
        self.state, self.emoji, self.sent, self.edited, self.asked = {}, {}, [], [], []
        msg = mock.Mock(id=1)
        self.chan = mock.Mock(id=5, send=mock.AsyncMock(side_effect=lambda **kw: self.sent.append(kw) or msg))
        partial = mock.Mock(edit=mock.AsyncMock(side_effect=lambda **kw: self.edited.append(kw)))
        self.chan.get_partial_message = mock.Mock(return_value=partial)
        self.guild = mock.Mock(get_channel=mock.Mock(return_value=self.chan))

    def ch(self, key):
        self.asked.append(key)
        return self.chan


def look(b, friends):
    with mock.patch.object(status.gaming, "psn_friends", return_value=friends), \
         mock.patch.object(status, "save_state"):
        asyncio.run(b.whos_on())


OFF = {"name": "FriendPSN2", "status": "offline", "game": None, "last": "2026-11-15T19:31:17+00:00"}
ON = {**OFF, "status": "availabletoplay", "game": "Minecraft"}


class WhosOn(unittest.TestCase):
    def test_card_then_a_friends_game_card(self):
        b = FakeBot()
        look(b, [OFF])
        self.assertEqual(len(b.sent), 1)  # the #online card
        look(b, [OFF])
        self.assertEqual(len(b.sent), 1)  # nothing changed: no edit, no post
        look(b, [ON])
        self.assertIn("minecraft", b.asked)
        self.assertEqual(len(b.sent), 2)  # Sam's game card, the same kind as Shane's
        self.assertIn("Sam", b.state["ps5_sessions"])
        look(b, [ON])
        self.assertEqual(len(b.sent), 2)  # still playing: no second card
        for _ in range(3):
            look(b, [OFF])
        self.assertNotIn("Sam", b.state["ps5_sessions"])  # ended: the card says how long


if __name__ == "__main__":
    unittest.main()
