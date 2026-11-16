"""#welcome's Let me in -> a request in #logs -> Shane's Approve / Deny (views.WelcomeCard, views.JoinDecision)."""
import asyncio
import datetime
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import discord  # noqa: E402

import views  # noqa: E402

OWNER = 1
CREW = mock.Mock(spec=discord.Role)
CREW.name = "Crew"


def member(uid=50, roles=()):
    m = mock.Mock(spec=discord.Member)
    m.id, m.display_name, m.mention, m.name = uid, "Alex", f"<@{uid}>", "pablo"
    m.roles = list(roles)
    m.created_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)
    m.display_avatar.url = "https://cdn.discordapp.com/embed/avatars/0.png"
    m.add_roles, m.kick, m.send = mock.AsyncMock(), mock.AsyncMock(), mock.AsyncMock()
    return m


def interaction(user):
    i = mock.Mock()
    i.user = user
    i.guild.roles = [CREW]
    i.guild.get_member = mock.Mock(return_value=user)
    i.client.owner_id = OWNER
    i.client.state = {}
    i.client.ch.return_value.send = mock.AsyncMock(return_value=mock.Mock(id=777))
    i.response.send_message = mock.AsyncMock()
    i.response.edit_message = mock.AsyncMock()
    i.response.is_done = mock.Mock(return_value=False)
    return i


def run(coro):
    with mock.patch.object(views, "save_state"):
        return asyncio.run(coro)


class Join(unittest.TestCase):
    def test_request_once(self):
        async def go():
            card, i = views.WelcomeCard(), interaction(member())
            await card.join(i)
            await card.join(i)
            return i
        i = run(go())
        self.assertEqual(i.client.ch.return_value.send.await_count, 1)  # one request card, not two
        self.assertEqual(i.client.state["join_requests"], {"50": 777})
        self.assertIn("Already asked", i.response.send_message.await_args_list[1].args[0])

    def test_crew_already_in(self):
        async def go():
            i = interaction(member(roles=[CREW]))
            await views.WelcomeCard().join(i)
            return i
        i = run(go())
        self.assertIn("already in", i.response.send_message.await_args.args[0])
        i.client.ch.return_value.send.assert_not_awaited()

    def test_approve_and_deny(self):
        async def go(act):
            m = member()
            i = interaction(m)
            i.user = mock.Mock(id=OWNER)  # Shane presses it
            i.client.state = {"join_requests": {"50": 777}}
            await views.JoinDecision(act, 50).callback(i)
            return m, i
        m, i = run(go("ok"))
        m.add_roles.assert_awaited_once()
        m.send.assert_awaited_once()  # "You're in!"
        self.assertEqual(i.client.state["join_requests"], {})
        m, _ = run(go("no"))
        m.kick.assert_awaited_once()

    def test_only_shane_decides(self):
        async def go():
            i = interaction(member())  # the newcomer tries to approve themself
            return await views.JoinDecision("ok", 50).interaction_check(i), i
        ok, i = run(go())
        self.assertFalse(ok)
        i.response.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
