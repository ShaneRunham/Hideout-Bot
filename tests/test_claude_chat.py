import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import claude_chat  # noqa: E402


class Chunks(unittest.TestCase):
    def test_short_reply_is_one_message(self):
        self.assertEqual(claude_chat.chunks("All good.\n\nNothing to do."), ["All good.\n\nNothing to do."])
        self.assertEqual(claude_chat.chunks(""), ["(no reply)"])

    def test_long_prose_splits_on_lines(self):
        text = "\n".join(f"Line {i} " + "word " * 20 for i in range(120))
        parts = claude_chat.chunks(text)
        self.assertGreater(len(parts), 1)
        self.assertTrue(all(len(p) <= 2000 for p in parts))
        self.assertEqual("\n".join(parts), text)

    def test_code_block_stays_fenced_in_every_part(self):
        code = [f"echo {i} " + "x" * 60 for i in range(100)]
        text = "Here:\n```bash\n" + "\n".join(code) + "\n```\nDone."
        parts = claude_chat.chunks(text)
        self.assertGreater(len(parts), 1)
        for p in parts:
            self.assertLessEqual(len(p), 2000)
            self.assertEqual(sum(line.startswith("```") for line in p.split("\n")) % 2, 0, p[:80])
        self.assertTrue(all(any(c in p for p in parts) for c in code))
        self.assertTrue(parts[1].startswith("```bash\n"))

    def test_one_very_long_line(self):
        parts = claude_chat.chunks("a" * 5000)
        self.assertTrue(all(len(p) <= 2000 for p in parts))
        self.assertEqual("".join(p.replace("\n", "") for p in parts), "a" * 5000)

    def test_one_line_snippet_is_not_a_block(self):
        self.assertEqual(claude_chat.chunks("```ls -la```\nthen this"), ["```ls -la```\nthen this"])


class Describe(unittest.TestCase):
    def test_steps(self):
        self.assertEqual(claude_chat.describe("Bash", {"command": "uptime\necho second line"}), "uptime")
        self.assertEqual(claude_chat.describe("Read", {"file_path": claude_chat.HOME + "/CLAUDE.md"}), "Read ~/CLAUDE.md")
        self.assertEqual(claude_chat.describe("WebSearch", {"query": "fedora 44"}), "WebSearch fedora 44")
        self.assertEqual(claude_chat.describe("TodoWrite", {}), "TodoWrite")


if __name__ == "__main__":
    unittest.main()
