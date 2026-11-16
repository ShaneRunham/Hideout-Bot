"""The 2026-11-12 review fixes: /getfile's secret guard, Claude attachments, the tick's order, the resume retry."""
import asyncio
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import bot  # noqa: E402
import commands  # noqa: E402
import claude_chat  # noqa: E402

H = bot.HOME


class GetfileGuard(unittest.TestCase):
    def test_ordinary_files_allowed(self):
        for p in ("", "/Downloads/photo.jpg", "/Documents/notes.md", "/homelab/README.md", "/tokenizer.py", "/Videos/broken.mp4"):
            self.assertTrue(commands._allowed(H + p), p)

    def test_secrets_and_outside_refused(self):
        for p in ("/homelab/discord-bot/.env", "/.ssh/id_ed25519", "/.config/x", "/homelab/alerts.env",
                  "/homelab/home-assistant/token", "/keys/server.pem", "/my_secret.txt", "/id_rsa"):
            self.assertFalse(commands._allowed(H + p), p)
        self.assertFalse(commands._allowed("/etc/passwd"))
        self.assertFalse(commands._allowed(H + "2/file"))  # a sibling folder that only shares the prefix


class Attachments(unittest.TestCase):
    def test_prompt_lists_files(self):
        self.assertEqual(claude_chat.with_files("hi", []), "hi")
        out = claude_chat.with_files("", ["/x/a.png"])
        self.assertIn("Have a look at this.", out)
        self.assertIn("- /x/a.png", out)


class TickOrder(unittest.TestCase):
    def test_home_assistant_still_gets_problems_when_discord_fails(self):
        b = bot.HomelabBot.__new__(bot.HomelabBot)
        b.nohen, b.graph_at = 0, 0
        b.graph_hist = mock.Mock()
        b.full_snapshot = lambda: {"ps3_up": False, "ps3": None}
        b.export_for_ha = mock.AsyncMock(return_value={"x": "y"})
        b.update_status = mock.AsyncMock(side_effect=OSError("Discord is down"))
        asyncio.run(bot.HomelabBot.tick.coro(b))
        b.export_for_ha.assert_awaited_once()
        b.update_status.assert_awaited_once_with(mock.ANY, {"x": "y"})


class ResumeRetry(unittest.TestCase):
    def run_ask(self, lines, session="old"):
        calls = []

        class Proc:
            returncode = 0

            def __init__(self):
                async def gen():
                    for l in lines.pop(0):
                        yield l.encode() + b"\n"
                self.stdout = gen()

            async def wait(self):
                return 0

        async def fake_exec(*args, **kw):
            calls.append(args)
            return Proc()

        with mock.patch("asyncio.create_subprocess_exec", fake_exec):
            r = asyncio.run(claude_chat.ask("hi", session, claude_chat.Run()))
        return r, calls

    def test_missing_conversation_starts_fresh(self):
        ok = '{"type":"result","result":"hello","session_id":"new","num_turns":1}'
        r, calls = self.run_ask([["No conversation found with session ID: old",
                                  '{"type":"result","is_error":true,"num_turns":0}'], [ok]])
        self.assertEqual((r["text"], r["session"], len(calls)), ("hello", "new", 2))
        self.assertNotIn("--resume", calls[1])

    def test_crash_is_not_retried(self):
        r, calls = self.run_ask([["Segmentation fault"]])
        self.assertEqual(len(calls), 1)
        self.assertIn("Claude didn't answer", r["text"])


if __name__ == "__main__":
    unittest.main()
