"""Claude in the bot: runs Claude Code headless (`claude -p`) on Shane's own Claude plan, never an API key, with the
same safety-checked permission mode ("auto") as his normal chats. bot.py owns the Discord side.

Settings (optional lines in .env):
    CLAUDE_MODEL=opus                  any Claude Code model name: opus (default), sonnet (lighter on the plan), fable...
    CLAUDE_PERMISSION_MODE=auto        auto (default: a safety check can block risky actions) or bypassPermissions (none)
"""
import asyncio
import json
import os
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
# Its own folder, so these conversations stay out of Shane's own session list. Claude Code still finds ~/CLAUDE.md
# (his notes about this PC) from here, because it reads CLAUDE.md files in every folder above the working one.
WORKDIR = os.path.join(HERE, "claude-workdir")
IDLE_RESET = 30 * 60  # a conversation continues until it has been quiet this long
TIMEOUT = 15 * 60
SYSTEM = """You are VICE, the assistant in Shane's private Discord server, running on his PC "fedora" as his own \
user. Every message comes from Shane, typed on his phone or the PC, and your reply is posted back into Discord.

- Write for a phone screen: lead with the answer, keep it short and plain. Discord markdown only: no tables and no \
HTML; put commands and output in code blocks. Stay under about 1,500 characters unless he asks for detail.
- You have the same tools and the same safety check as his normal Claude Code chats. sudo needs a password you \
don't have: give Shane the exact command to run instead.
- Before anything destructive or hard to undo (deleting, overwriting, reinstalling, rebooting, changing a service or \
a config he didn't ask about), say what you would do and wait for his yes in his next message.
- Never print passwords, tokens or keys, including the ones in .env files.
- If the safety check blocks an action, say so plainly, and give him the command if it's one he could run himself.
- His notes about this PC are in your instructions (~/CLAUDE.md); more are in \
~/.claude/projects/-home-shanerunham/memory/."""


def _env() -> dict:
    """Claude's environment: the plan's login is used (no API key), and the bot's own token stays out of its shell."""
    drop = ("ANTHROPIC_API_KEY", "DISCORD_BOT_TOKEN", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")
    env = {k: v for k, v in os.environ.items() if k not in drop and not k.startswith("CLAUDE_CODE_SSE")}
    env["PATH"] = f"{HOME}/.local/bin:" + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def describe(tool: str, args: dict) -> str:
    """One short line per thing Claude did, for the progress note and #logs."""
    if tool == "Bash":
        return (args.get("command") or "").strip().split("\n")[0][:160]
    target = next((args[k] for k in ("file_path", "path", "pattern", "query", "url") if args.get(k)), "")
    return f"{tool} {str(target).replace(HOME, '~', 1)}".strip()[:160]


class Run:
    """One question to Claude: `steps` fills in while it works, `stop()` ends it early."""

    def __init__(self):
        self.proc: asyncio.subprocess.Process | None = None
        self.steps: list[str] = []
        self.stopped = False

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()


async def ask(prompt: str, session: str | None, run: Run, on_step=None) -> dict:
    """Ask Claude, continuing `session` when given. Returns {"ok", "text", "session", "denied", "seconds"}:
    `session` is the conversation to continue next time, `denied` what the safety check blocked."""
    os.makedirs(WORKDIR, exist_ok=True)
    args = [shutil.which("claude", path=_env()["PATH"]) or "claude", "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--model", os.environ.get("CLAUDE_MODEL", "opus"),
            "--permission-mode", os.environ.get("CLAUDE_PERMISSION_MODE", "auto"), "--permission-prompts", "none",
            "--setting-sources", "project",  # not the user settings: no JARVIS voice hook, no extra plugins or skills
            "--strict-mcp-config", "--append-system-prompt", SYSTEM]
    if session:
        args += ["--resume", session]
    started = time.time()
    # stream-json puts a whole tool result on one line, so the line limit has to be generous
    run.proc = await asyncio.create_subprocess_exec(
        *args, cwd=WORKDIR, env=_env(), stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, limit=64 * 1024 * 1024)
    result, noise = None, []

    async def read():
        nonlocal result
        async for line in run.proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                noise.append(line.decode(errors="replace").strip())
                continue
            if event.get("type") == "assistant":
                for block in event["message"].get("content", []):
                    if block.get("type") == "tool_use":
                        run.steps.append(describe(block["name"], block.get("input") or {}))
                        if on_step:
                            await on_step()
            elif event.get("type") == "result":
                result = event

    timed_out = False
    try:
        await asyncio.wait_for(read(), TIMEOUT)
    except asyncio.TimeoutError:
        timed_out = True
        run.proc.kill()
    await run.proc.wait()
    out = {"ok": False, "session": session, "denied": [], "seconds": time.time() - started}
    if run.stopped:
        return {**out, "text": "Stopped."}
    if timed_out:
        return {**out, "text": f"That took longer than {TIMEOUT // 60} minutes, so I stopped it."}
    if session and any("No conversation found" in n for n in noise):
        return await ask(prompt, None, run, on_step)  # the old conversation is gone: start a new one
    # (any other failure is reported, not retried: Claude may already have run commands)
    if result is None:
        return {**out, "session": None, "text": "Claude didn't answer" + (f": {noise[-1][:300]}" if noise else ".")}
    return {"ok": not result.get("is_error"), "text": (result.get("result") or "").strip() or "(no reply)",
            "session": result.get("session_id"), "seconds": time.time() - started,
            "denied": [describe(d.get("tool_name", "?"), d.get("tool_input") or {})
                       for d in result.get("permission_denials") or []]}


def with_files(prompt: str, files) -> str:
    """The message for Claude, with any Discord attachments (already saved on the PC) listed by path."""
    if not files:
        return prompt
    listed = "\n".join(f"- {p}" for p in files)
    return (f"{prompt.strip() or 'Have a look at this.'}\n\nShane attached these in Discord; they're saved on the PC "
            f"(the Read tool opens them, images included):\n{listed}")


def chunks(text: str, limit: int = 1900) -> list[str]:
    """Split a reply into Discord-sized messages on line breaks, keeping a code block fenced in every part."""
    if not text.strip():
        return ["(no reply)"]
    out, cur, size, fence = [], [], 0, None  # fence: the opening ``` line of the code block we're inside

    def flush():
        nonlocal cur, size
        out.append("\n".join(cur) + ("\n```" if fence else ""))
        cur, size = ([fence], len(fence) + 1) if fence else ([], 0)

    for line in text.split("\n"):
        is_fence = line.lstrip().startswith("```") and line.count("```") == 1  # not a one-line ```snippet```
        for piece in [line[i:i + limit - 100] for i in range(0, len(line), limit - 100)] or [""]:
            closing = is_fence and fence is not None
            if size + len(piece) + 1 > limit - 4 and cur != ([fence] if fence else []) and not closing:
                flush()
            cur.append(piece)
            size += len(piece) + 1
        if is_fence:
            fence = None if fence else line.strip()
    if cur != ([fence] if fence else []):
        out.append("\n".join(cur) + ("\n```" if fence else ""))
    return out
