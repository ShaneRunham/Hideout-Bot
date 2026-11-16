"""The slash commands (/getfile, /clip, /type, /note, /remind, /playtime, /radio, ...) and the
right-click "Copy to PC clipboard"."""
from __future__ import annotations

import asyncio
import datetime
import io
import os
import time

import discord
from discord import app_commands

import cards
import keyboard
import playtime
import radio
import remind

from typing import TYPE_CHECKING
from common import HOME, LONDON, OwnerView, SECRET_NAME, is_crew, owner_only, run, save_attachments, save_state

if TYPE_CHECKING:
    from bot import HomelabBot


MAX_UPLOAD = 10 * 1024 * 1024  # Discord's limit for bots in an unboosted server
_long_paths: dict[str, str] = {}  # "#n" -> full path, for paths too long for Discord's 100-character choices


def _resolve(path: str) -> str:
    path = _long_paths.get(path, path).strip()
    return os.path.realpath(os.path.expanduser(path if path.startswith(("~", "/")) else "~/" + path))


def _allowed(full: str) -> bool:
    """In the home folder, not under a hidden folder (.ssh, .config…) and not named like a secret."""
    if full != HOME and not full.startswith(HOME + os.sep):
        return False
    hidden = any(p.startswith(".") for p in os.path.relpath(full, HOME).split(os.sep) if p != ".")
    return not hidden and not SECRET_NAME.search(os.path.basename(full))


def _size(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e5 else f"{n / 1e3:.0f} KB"


def _listing(folder: str) -> list[tuple[str, str, str]]:
    """(label, description, full path) for a folder: up a level, then subfolders, then newest files; max 25."""
    try:
        entries = [e for e in os.scandir(folder) if _allowed(e.path)]
    except OSError:
        return []

    def mtime(e):
        try:
            return e.stat().st_mtime
        except OSError:
            return 0
    out = []
    if os.path.realpath(folder) != HOME:
        out.append(("Up one folder", os.path.dirname(folder).replace(HOME, "~", 1) + "/", os.path.dirname(folder)))
    dirs = sorted((e for e in entries if e.is_dir()), key=lambda e: e.name.lower())
    files = sorted((e for e in entries if e.is_file()), key=mtime, reverse=True)
    room = 25 - len(out)
    dirs = dirs[:max(8, room - len(files))]
    for e in dirs:
        out.append((f"{e.name}/"[:100], "folder", e.path))
    for e in files[:25 - len(out)]:
        size = e.stat().st_size
        out.append((e.name[:100], f"{'too big · ' if size > MAX_UPLOAD else ''}{_size(size)}", e.path))
    return out


async def _send_file(interaction: discord.Interaction, full: str):
    if not _allowed(os.path.realpath(full)):
        return await interaction.followup.send("That one stays on the PC: it looks like a key, token or private "
                                               "setting.", ephemeral=True)
    size = os.path.getsize(full)
    if size > MAX_UPLOAD:
        return await interaction.followup.send(
            f"`{os.path.basename(full)}` is {_size(size)}; Discord only lets bots send up to 10 MB here.",
            ephemeral=True)
    await interaction.followup.send(file=discord.File(full), ephemeral=True)


class FileBrowser(OwnerView):
    """A drop-down of a folder's contents: pick a file to receive it, or a folder to open it."""

    def __init__(self, folder: str):
        super().__init__(timeout=600)
        self.show(folder)

    def show(self, folder: str):
        self.folder = folder
        self.items = _listing(folder)
        self.clear_items()
        select = discord.ui.Select(placeholder="Pick a file to send, or a folder to open…",
                                   options=[discord.SelectOption(label=lbl, description=desc, value=str(i))
                                            for i, (lbl, desc, _) in enumerate(self.items)] or
                                   [discord.SelectOption(label="(empty folder)", value="-1")])
        select.callback = self.picked
        self.add_item(select)

    def text(self) -> str:
        return (f"**{self.folder.replace(HOME, '~', 1)}/**  (newest first; files over 10 MB can't be sent)"
                if self.folder != HOME else "**~/**  (newest first; files over 10 MB can't be sent)")

    async def picked(self, interaction: discord.Interaction):
        i = int(interaction.data["values"][0])
        if i < 0:
            return await interaction.response.defer()
        path = self.items[i][2]
        if os.path.isdir(path):
            self.show(path)
            return await interaction.response.edit_message(content=self.text(), view=self)
        await interaction.response.defer(ephemeral=True, thinking=True)
        await _send_file(interaction, path)


@app_commands.command(description="Get a file from the PC: browse folders, or type a path (max 10 MB)")
@app_commands.describe(path="Optional: a file or folder (suggestions as you type). Empty = Downloads")
@owner_only()
async def getfile(interaction: discord.Interaction, path: str = "~/Downloads"):
    full = _resolve(path)
    if not _allowed(full):
        return await interaction.response.send_message("Only files in your home folder, and not keys, tokens or "
                                                       "hidden folders.", ephemeral=True)
    if os.path.isdir(full):
        view = FileBrowser(full)
        return await interaction.response.send_message(view.text(), view=view, ephemeral=True)
    if not os.path.isfile(full):
        return await interaction.response.send_message(
            f"`{full.replace(HOME, '~', 1)}` doesn't exist.", ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    await _send_file(interaction, full)


@getfile.autocomplete("path")
async def getfile_complete(interaction: discord.Interaction, current: str):
    typed = _long_paths.get(current, current)
    base = os.path.expanduser(typed if typed.startswith(("~", "/")) else "~/" + typed)
    folder, part = os.path.split(base)
    if not os.path.isdir(folder):  # "downloads/" -> ~/Downloads: match folder names ignoring case
        fixed = "/"
        for piece in folder.strip("/").split("/"):
            try:
                fixed = os.path.join(fixed, next(n for n in os.listdir(fixed) if n.lower() == piece.lower()))
            except (OSError, StopIteration):
                return []
        folder = fixed
    if not _allowed(os.path.realpath(folder)):
        folder = HOME
    try:
        entries = [e for e in os.scandir(folder) if _allowed(e.path) and part.lower() in e.name.lower()]
    except OSError:
        return []

    def mtime(e):
        try:
            return e.stat().st_mtime
        except OSError:
            return 0
    dirs = sorted((e for e in entries if e.is_dir()), key=lambda e: e.name.lower())
    files = sorted((e for e in entries if e.is_file()), key=mtime, reverse=True)
    out = []
    for e in (dirs[:8] + files)[:25]:
        p = os.path.join(folder, e.name).replace(HOME, "~", 1) + ("/" if e.is_dir() else "")
        if e.is_dir():
            label = p
        else:
            size = e.stat().st_size
            label = f"{'too big · ' if size > MAX_UPLOAD else ''}{_size(size)} · {p}"
        if len(label) > 100:
            label = label[:48] + "…" + label[-51:]
        value = p
        if len(p) > 100:
            value = f"#{len(_long_paths)}"
            _long_paths[value] = p
        out.append(app_commands.Choice(name=label, value=value))
    return out


@app_commands.command(description="Rebuild missing channels, the status message and the control panel")
@owner_only()
async def setup(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    bot: HomelabBot = interaction.client
    await bot.build_server()
    await bot.update_status(await asyncio.to_thread(bot.full_snapshot), bot.problems or None)
    await interaction.followup.send("Channels, #status and #control checked.", ephemeral=True)


@owner_only()
async def copy_to_clipboard(interaction: discord.Interaction, message: discord.Message):
    """Right-click (long-press) a message > Apps > Copy to PC clipboard."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    image = next((a for a in message.attachments if (a.content_type or "").startswith("image/")), None)
    if message.content:
        data, kind, what = message.content.encode(), "text/plain;charset=utf-8", "Text"
    elif image:
        data, kind, what = await image.read(), image.content_type, "Image"
    else:
        return await interaction.followup.send("Nothing to copy (no text or image).", ephemeral=True)
    proc = await asyncio.create_subprocess_exec("wl-copy", "--type", kind, stdin=asyncio.subprocess.PIPE,
                                                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await proc.communicate(data)  # wl-copy keeps serving the clipboard in the background
    await interaction.followup.send(f"{what} copied to the PC's clipboard." if proc.returncode == 0
                                    else "Couldn't reach the PC's clipboard.", ephemeral=True)


@app_commands.command(description="Get what's on the PC's clipboard (text or image)")
@owner_only()
async def clip(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    code, types = await run("wl-paste", "--list-types", timeout=5)
    if code != 0:
        return await interaction.followup.send("The clipboard is empty.", ephemeral=True)
    img = next((t for t in types.split() if t.startswith("image/")), None)
    if img:
        proc = await asyncio.create_subprocess_exec("wl-paste", "--type", img, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.DEVNULL)
        data, _ = await asyncio.wait_for(proc.communicate(), 10)
        ext = img.split("/")[1].split(";")[0]
        return await interaction.followup.send(file=discord.File(io.BytesIO(data), f"clipboard.{ext}"), ephemeral=True)
    code, text = await run("wl-paste", "--no-newline", timeout=5)
    if not text:
        return await interaction.followup.send("The clipboard is empty.", ephemeral=True)
    if len(text) > 1900:
        return await interaction.followup.send("Clipboard (long, as a file):",
                                               file=discord.File(io.BytesIO(text.encode()), "clipboard.txt"),
                                               ephemeral=True)
    await interaction.followup.send(f"Clipboard:\n```\n{text.replace('```', '`​``')}\n```", ephemeral=True)


@app_commands.command(name="type", description="Type text on the PC, into whatever has focus")
@app_commands.describe(text="What to type (not passwords: Discord keeps a copy)", enter="Press Enter afterwards")
@owner_only()
async def type_cmd(interaction: discord.Interaction, text: app_commands.Range[str, 1, 500], enter: bool = False):
    if bad := keyboard.unsupported(text):
        return await interaction.response.send_message(f"Can't type these: {bad} (GB keyboard characters only).",
                                                       ephemeral=True)
    await interaction.response.defer(ephemeral=True, thinking=True)
    await asyncio.to_thread(keyboard.type_text, text, enter)
    await interaction.followup.send(f"Typed {len(text)} characters" + (" and pressed Enter." if enter else "."),
                                    ephemeral=True)
    await interaction.client.post("logs", f"/type: {len(text)} characters" + (" + Enter" if enter else ""))


@app_commands.command(description="Clear recent messages in this channel (keeps #status and the control panel)")
@app_commands.describe(count="How many recent messages to check (1-200)")
@owner_only()
async def cleanup(interaction: discord.Interaction, count: app_commands.Range[int, 1, 200] = 50):
    bot: HomelabBot = interaction.client
    keep = {bot.state.get("status_card"), bot.state.get("control_card"), bot.state.get("claude_card"),
            bot.state.get("commands_card")}
    await interaction.response.defer(ephemeral=True, thinking=True)
    deleted = await interaction.channel.purge(limit=count, check=lambda m: m.id not in keep and not m.pinned)
    await interaction.followup.send(f"Cleared {len(deleted)} message(s).", ephemeral=True)


@app_commands.command(description="Ask Claude on the PC (the same conversation as #claude)")
@app_commands.describe(question="What to ask or tell Claude", file="Optional: an image or file for Claude to look at")
@owner_only()
async def ask(interaction: discord.Interaction, question: str, file: discord.Attachment | None = None):
    await interaction.response.send_message("> " + question[:1800].replace("\n", "\n> ")
                                            + (f"\n-# with {file.filename}" if file else ""),
                                            allowed_mentions=discord.AllowedMentions.none())
    await interaction.client.ask_claude(question, interaction.channel,
                                        await save_attachments([file] if file else []))


NOTES = os.path.expanduser("~/Documents/notes.md")


def save_note(text: str):
    """Append a dated note to ~/Documents/notes.md (#claude can read and search it)."""
    os.makedirs(os.path.dirname(NOTES), exist_ok=True)
    with open(NOTES, "a", encoding="utf-8") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} {text}\n")


@app_commands.command(description="Jot a note: saved to #notes and ~/Documents/notes.md on the PC")
@app_commands.describe(text="The note")
@owner_only()
async def note(interaction: discord.Interaction, text: str):
    await asyncio.to_thread(save_note, text)
    bot: HomelabBot = interaction.client
    await bot.post("notes", f"📝 {text}")
    await interaction.response.send_message("Noted.", ephemeral=True)


@app_commands.command(name="remind", description="Remind me: here in Discord and as a card on the TV")
@app_commands.describe(when="30m, 2h, 1h30m, or a time like 18:00", text="What to remind you about")
@owner_only()
async def remind_cmd(interaction: discord.Interaction, when: str, text: str):
    now = datetime.datetime.now(LONDON)
    t = remind.due(when, now)
    if t is None:
        return await interaction.response.send_message("I didn't get the time. Try `30m`, `2h`, `1h30m` or `18:00`.", ephemeral=True)
    bot: HomelabBot = interaction.client
    bot.state.setdefault("reminders", []).append(
        {"at": t.timestamp(), "set": now.timestamp(), "text": text[:120], "channel": interaction.channel_id})
    save_state(bot.state)
    await interaction.response.send_message(f"I'll remind you {remind.say_when(t, now)}: {text}", ephemeral=True)


def reminder_lines(bot: "HomelabBot") -> str:
    now = datetime.datetime.now(LONDON)
    rs = sorted(bot.state.get("reminders", []), key=lambda r: r["at"])
    return "\n".join(f"🔔 **{remind.say_when(datetime.datetime.fromtimestamp(r['at'], LONDON), now)}** · {r['text']}"
                     for r in rs) or "No reminders set. Add one with `/remind`."


class ReminderList(cards.Card):
    """/reminders: a card with the pending ones and a menu to cancel one."""

    def __init__(self, bot: "HomelabBot", note: str = ""):
        now = datetime.datetime.now(LONDON)
        rs = sorted(bot.state.get("reminders", []), key=lambda r: r["at"])[:25]
        items = [cards.header("Reminders", note or None), cards.text(reminder_lines(bot))]
        if rs:
            menu = discord.ui.Select(placeholder="Cancel one…", options=[discord.SelectOption(
                label=r["text"][:100], value=repr(r["at"]),
                description=remind.say_when(datetime.datetime.fromtimestamp(r["at"], LONDON), now)) for r in rs])
            menu.callback = lambda interaction: self.cancel(interaction, menu)
            items.append(cards.row(menu))
        super().__init__(cards.card("accent", *items), timeout=300)

    async def cancel(self, interaction: discord.Interaction, select: discord.ui.Select):
        bot: HomelabBot = interaction.client
        at = float(select.values[0])
        gone = [r for r in bot.state.get("reminders", []) if r["at"] == at]
        bot.state["reminders"] = [r for r in bot.state.get("reminders", []) if r["at"] != at]
        save_state(bot.state)
        await interaction.response.edit_message(view=ReminderList(bot, f"Cancelled: {gone[0]['text']}" if gone else ""))


@app_commands.command(description="Your reminders, and cancel one")
@owner_only()
async def reminders(interaction: discord.Interaction):
    bot: HomelabBot = interaction.client
    await interaction.response.send_message(view=ReminderList(bot), ephemeral=True)


@app_commands.command(description="Start a fresh conversation with Claude")
@owner_only()
async def new(interaction: discord.Interaction):
    bot: HomelabBot = interaction.client
    bot.state.pop("claude_session", None)
    save_state(bot.state)
    await interaction.response.send_message("Fresh conversation. Claude won't remember the last one.", ephemeral=True)


@app_commands.command(name="playtime", description="PS5 play time over the last 7 days, per game and per day")
@owner_only()
async def playtime_cmd(interaction: discord.Interaction):
    games, per_day = await asyncio.to_thread(playtime.week)
    total = sum(games.values())
    items = [cards.header("PS5 this week", f"{playtime.fmt(total)} in the last 7 days" if total else
                          "Nothing played in the last 7 days (the log started on 13 Nov 2026)")]
    if games:
        top = max(per_day.values()) or 1
        items += [cards.divider(),
                  cards.text("### 🎮 Games", *(f"**{g}** · {playtime.fmt(m)}" for g, m in list(games.items())[:10])),
                  cards.text("### 📅 Days", *(
                      f"{datetime.date.fromisoformat(d).strftime('%a')}  {'🟪' * round(m / top * 8) or '·'}  "
                      f"{playtime.fmt(m) if m else ''}" for d, m in reversed(per_day.items())))]
    await interaction.response.send_message(view=cards.Card(cards.card("accent", *items)), ephemeral=True)


@app_commands.command(name="radio", description="Vice Radio in your voice channel (or the Vice Radio one): play, skip or stop")
@app_commands.choices(action=[app_commands.Choice(name="Play", value="play"),
                              app_commands.Choice(name="Skip", value="skip"),
                              app_commands.Choice(name="Stop", value="stop")])
@app_commands.check(is_crew)  # Shane and the Crew
async def radio_cmd(interaction: discord.Interaction, action: str = "play"):
    bot: HomelabBot = interaction.client
    await interaction.response.defer(ephemeral=True)
    if action == "skip":  # the same skip as the TV and the HA panel
        if not await asyncio.to_thread(radio.may_skip, interaction.user.id, bot.owner_id):
            await interaction.followup.send(radio.SKIP_BLOCKED, ephemeral=True)
            return
        await asyncio.to_thread(radio.skip)
        await interaction.followup.send("Skipped: the next song starts in a few seconds.", ephemeral=True)
        return
    if action == "stop":
        await bot.radio_stop()
        await interaction.followup.send("Vice Radio is off.", ephemeral=True)
        return
    member = bot.guild.get_member(interaction.user.id)
    channel = member.voice.channel if member and member.voice and member.voice.channel else await bot.radio_channel()
    await bot.radio_start(channel)
    await interaction.followup.send(f"Vice Radio is on in {channel.mention}. It leaves by itself under a minute after "
                                    "everyone else does, and clears its messages.", ephemeral=True)


COMMANDS = (getfile, setup, clip, type_cmd, cleanup, ask, new, note, playtime_cmd, remind_cmd, reminders, radio_cmd)
