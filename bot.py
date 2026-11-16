#!/usr/bin/env python3
"""Shane's personal homelab Discord bot: builds its channels in a fresh server, keeps a live #status message, hands
the current problems to Home Assistant, has #control buttons, talks to Claude in #claude and saves files dropped in
#files. Only answers the application's owner."""
import asyncio
import logging
import os
import time

import discord
from discord import app_commands
from dotenv import load_dotenv

import claude_chat
import collect
import gaming
import graphs
import wanted

from common import BOT_NAME, HERE, HOME, INBOX, URL_RE, app_command_error, load_state, log, run, save_attachments, save_state
from views import ControlPanel, JoinDecision, StopClaude, WelcomeCard
from commands import COMMANDS, copy_to_clipboard, radio_cmd, save_note
from server import ServerMixin
from status import StatusMixin
from radio_voice import RadioMixin


class HomelabBot(ServerMixin, StatusMixin, RadioMixin, discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # to see attachments in #files
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.tree.error(app_command_error)
        self.state = load_state()
        self.owner_id: int | None = None
        self.guild: discord.Guild | None = None
        self.hot_count = 0
        self.nohen = 0
        self.radio_down, self.radio_healed = 0, 0.0  # minutes without the radio stream; last auto-restart
        self.ha_fails = 0
        self.ready_once = False
        self.graph_hist = graphs.History(os.path.join(HERE, "history.json"))
        self.graph_at = 0.0
        self.look = None  # last (colour, words) applied to the presence
        self.renamed_at = 0.0
        self.emoji: dict[str, str] = {}  # status-light key -> custom emoji
        self.problems: dict[str, str] = {}  # the latest problems handed to Home Assistant
        self.wanted = wanted.load()  # Wanted Level state (wanted.py, wanted.json)
        self.claude_lock = asyncio.Lock()  # one question to Claude at a time
        self.radio_msg: discord.Message | None = None  # the /radio now-playing card
        self.radio_song: tuple | None = None
        self.radio_lock = asyncio.Lock()  # one now-playing card at a time
        self.radio_empty_since: float | None = None

    # ---------- setup ----------
    async def setup_hook(self):
        self.add_view(ControlPanel(self, self.state.get("channels", {}).get("logs", 0)))  # buttons keep working after restarts
        self.add_view(WelcomeCard())  # the Let me in button in #welcome
        self.add_dynamic_items(JoinDecision)  # Approve / Deny on join requests in #logs
        app = await self.application_info()
        self.owner_id = app.team.owner_id if app.team else app.owner.id
        # Everything but /radio is hidden from the Crew's command list (needs Administrator, which the owner always
        # has); the owner checks still refuse anyone else who finds them.
        admin = discord.Permissions(administrator=True)
        for cmd in COMMANDS:
            if cmd is not radio_cmd:
                cmd.default_permissions = admin
            self.tree.add_command(cmd)
        menu = app_commands.ContextMenu(name="Copy to PC clipboard", callback=copy_to_clipboard)
        menu.default_permissions = admin
        self.tree.add_command(menu)

    async def on_ready(self):
        if self.ready_once:
            return
        self.ready_once = True
        self.guild = next((g for g in self.guilds if g.owner_id == self.owner_id), None)
        if not self.guild:
            log.error("Not in a server you own yet. Invite me with the link in README.md.")
            return
        self.tree.copy_global_to(guild=self.guild)
        await self.tree.sync(guild=self.guild)
        self.tree.clear_commands(guild=None)  # commands live on the server only; this also removes any
        await self.tree.sync()                # left-over global ones (the old bot's 27 commands)
        await self.build_server()
        await self.brand()
        await self.boss_role()
        await self.load_emojis()
        try:
            await self.quiet_notifications()
        except discord.HTTPException as e:
            log.warning("Couldn't change the notification default: %s", e)
        await self.post("logs", f"{BOT_NAME} is back online on {collect.platform.node()}.")
        self.tick.start()
        self.gta_news.start()
        self.reminders.start()

    async def on_guild_join(self, guild: discord.Guild):
        if not self.guild and guild.owner_id == self.owner_id:
            self.ready_once = False
            await self.on_ready()


    # ---------- Claude ----------
    async def ask_claude(self, prompt: str, channel: discord.abc.Messageable, files: list[str] = ()):
        """Pass one message to Claude (continuing the conversation unless it has gone quiet) and post the answer.
        files: attachments already saved on the PC, which Claude is told about."""
        quiet = discord.AllowedMentions.none()
        said, prompt = prompt, claude_chat.with_files(prompt, files)
        if self.claude_lock.locked():
            await channel.send("-# Still on the last one. This is next.")
        async with self.claude_lock:
            fresh = time.time() - self.state.get("claude_at", 0) > claude_chat.IDLE_RESET
            run, note, edited = claude_chat.Run(), None, 0.0

            async def on_step():  # one small note that follows what Claude is doing, with a Stop button
                nonlocal note, edited
                step = run.steps[-1][:120].replace("`", "'")
                try:
                    if not note:
                        note = await channel.send(f"-# Step 1: `{step}`", view=StopClaude(self, run))
                    elif time.time() - edited > 2:
                        await note.edit(content=f"-# Step {len(run.steps)}: `{step}`")
                        edited = time.time()
                except discord.HTTPException:
                    pass

            async with channel.typing():
                r = await claude_chat.ask(prompt, None if fresh else self.state.get("claude_session"), run, on_step)
            self.state["claude_session"], self.state["claude_at"] = r["session"], time.time()
            save_state(self.state)
            if note:
                n = len(run.steps)
                try:
                    await note.edit(content=f"-# {n} step{'s' if n != 1 else ''} · {r['seconds']:.0f} s", view=None)
                except discord.HTTPException:
                    pass
            for part in claude_chat.chunks(r["text"]):
                await channel.send(part, allowed_mentions=quiet, suppress_embeds=True)
            if r["denied"]:
                await channel.send("-# The safety check blocked: " + ", ".join(
                    "`" + d[:80].replace("`", "'") + "`" for d in r["denied"][:3]), allowed_mentions=quiet)
            if run.steps:
                steps = "\n".join(run.steps)[:1500].replace("```", "'''")
                await self.post("logs", f"Claude took {len(run.steps)} step(s) for “{said[:100]}”:\n```\n{steps}\n```",
                                allowed_mentions=quiet)

    # ---------- #links, #claude, #files ----------
    async def on_message(self, m: discord.Message):
        if m.author.id != self.owner_id:
            return
        chans = self.state.get("channels", {})
        if m.channel.id == chans.get("links"):
            urls = URL_RE.findall(m.content)
            for u in urls:
                await run("systemd-run", "--user", "--collect", "--quiet", "xdg-open", u, timeout=15)
            if urls:
                await m.add_reaction("✅")
                await self.post("logs", f"Opened {len(urls)} link(s) on the PC")
            return
        if m.channel.id == chans.get("tv") and m.content.strip():
            note = await m.reply("Starting it on the TV… (a few seconds if the TV was off)", mention_author=False)
            try:
                title = await asyncio.to_thread(gaming.play_on_tv, m.content.strip())
            except Exception as e:  # noqa: BLE001 - say what went wrong
                return await note.edit(content=f"Couldn't play that: {e}")
            await m.add_reaction("✅")
            await note.edit(content=f"Playing on the TV: **{title}**")
            return await self.post("logs", f"TV: playing {title}")
        if m.channel.id == chans.get("notes") and m.content.strip():
            await asyncio.to_thread(save_note, m.content.strip())
            return await m.add_reaction("📝")
        if m.channel.id == chans.get("claude"):
            if m.content.strip() or m.attachments:
                await self.ask_claude(m.content, m.channel, await save_attachments(m.attachments))
            return
        if not m.attachments or m.channel.id != chans.get("files"):
            return
        saved = [p.replace(HOME, "~", 1) for p in await save_attachments(m.attachments)]
        await m.add_reaction("✅")
        await m.reply("Saved: " + ", ".join(f"`{p}`" for p in saved), mention_author=False)
        await self.post("logs", f"Saved {len(saved)} file(s) to `{INBOX.replace(HOME, '~')}`")


def main():
    load_dotenv(os.path.join(HERE, ".env"))
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Put DISCORD_BOT_TOKEN in .env")
    discord.utils.setup_logging(level=logging.INFO, root=True)
    HomelabBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
