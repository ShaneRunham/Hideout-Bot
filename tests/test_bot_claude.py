"""The Discord side of Claude (HomelabBot.ask_claude) with Discord and Claude both faked."""
import asyncio
import contextlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot  # noqa: E402


class FakeMessage:
    def __init__(self, content, view):
        self.content, self.view = content, view

    async def edit(self, **kw):
        self.content, self.view = kw.get("content", self.content), kw.get("view", self.view)


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kw):
        self.sent.append(FakeMessage(content, kw.get("view")))
        return self.sent[-1]

    def typing(self):
        return contextlib.nullcontext()


class FakeBot:
    def __init__(self):
        self.state, self.claude_lock, self.logged = {}, asyncio.Lock(), []

    async def post(self, channel, text=None, **kw):
        self.logged.append((channel, text))


class AskClaude(unittest.IsolatedAsyncioTestCase):
    async def test_steps_answer_and_log(self):
        asked = []

        async def fake_ask(prompt, session, run, on_step):
            asked.append(session)
            for step in ("uptime", "df -h"):
                run.steps.append(step)
                await on_step()
            return {"ok": True, "text": "Line one\n" + "word " * 600, "session": "abc", "denied": ["rm -rf ~/x"],
                    "seconds": 3.2}

        real_ask, real_save = bot.claude_chat.ask, bot.save_state
        bot.claude_chat.ask, bot.save_state = fake_ask, lambda state: None
        try:
            me, channel = FakeBot(), FakeChannel()
            await bot.HomelabBot.ask_claude(me, "how full are the disks?", channel)
            await bot.HomelabBot.ask_claude(me, "and now?", FakeChannel())
        finally:
            bot.claude_chat.ask, bot.save_state = real_ask, real_save
        note, *rest = channel.sent
        self.assertEqual(note.content, "-# 2 steps · 3 s")          # the progress note ends as a one-line summary
        self.assertIsNone(note.view)                                 # ...with its Stop button gone
        self.assertTrue(all(len(m.content) <= 2000 for m in rest))
        self.assertGreater(len(rest), 2)                             # a long answer in parts, then the blocked note
        self.assertEqual(rest[-1].content, "-# The safety check blocked: `rm -rf ~/x`")
        self.assertEqual(asked, [None, "abc"])                       # the second message continues the conversation
        self.assertEqual(me.logged[0][0], "logs")
        self.assertIn("uptime\ndf -h", me.logged[0][1])


if __name__ == "__main__":
    unittest.main()
