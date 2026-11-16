"""Shared by the bot modules: paths and names, the server layout and colours, state.json, small helpers,
and the owner-only checks every button and command goes through."""
from __future__ import annotations

import asyncio
import zoneinfo
import json
import logging
import os
import re

import discord
from discord import app_commands

import collect

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import HomelabBot

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
INBOX = os.path.expanduser("~/Downloads/Discord")
HOME = os.path.expanduser("~")
HA_STATE = os.path.join(HOME, "homelab/home-assistant/config/homelab-state.json")  # read by Home Assistant
GOVEE = os.path.expanduser("~/.local/bin/ha-light")  # the light goes through Home Assistant
PHONE_CAM = os.path.expanduser("~/.local/bin/phone-cam")
SUNSHINE = "app-dev.lizardbyte.app.Sunshine.service"
PIXEL_KDECONNECT = "00000000000000000000000000000000"  # Pixel 9 Pro XL in `kdeconnect-cli -l`
# Channel list (Shane's pick 2026-11-16): grouped by what he does there, an icon and a divider per channel.
# Categories and channels are tracked by ID (state.json "categories"/"channels"), so names, groups and order can
# change freely: every start renames, regroups and reorders to match this. #status's icon and name follow the
# health (apply_look). The Vice Radio voice channel (key "radio") is made by /radio the first time.
LAYOUT = [  # (category key, category name, [(channel key, channel name, topic)])
    # Order set by Shane by hand in Discord (2026-11-16): HELP, WELCOME, LOUNGE, GAMING, then his private ones
    ("help", "── HELP ──", [
        ("crew_help", "❓┃crew-guide", "What you can do here: the channels, /radio and a couple of tips"),
        ("commands", "📖┃commands", "Everything VICE can do, in one pinned message")]),
    # WELCOME is the only thing a newcomer sees: read-only, with a "Let me in" button that gives the Crew role
    ("welcome", "── WELCOME ──", [
        ("welcome", "🚪┃welcome", "Start here: press Let me in on the card below")]),
    ("lounge", "── LOUNGE ──", [  # and the Vice Radio voice channel
        ("crew_general", "💬┃general", "Chat for everyone here")]),
    # GAMING and LOUNGE are open to the Crew role (Shane's friend and partner, 2026-11-16); everything else stays
    # private to Shane and the bot. Their voice channels are in VOICE.
    ("gaming", "── GAMING ──", [
        ("online", "🟢┃online", "Who's on PSN and Switch right now and what they're playing (kept up to date by the bot)"),
        ("ps5", "🎮┃ps5-games", "PS5 games together: what to play, and a card when anyone starts a game"),
        ("switch", "🕹️┃switch-games", "Switch games together: what to play, and a card when anyone starts a game"),
        ("minecraft", "⛏️┃minecraft", "Minecraft: worlds, builds and plans")]),
    ("live", "── LIVE ──", [
        ("status", "📊┃status", "Live PC and homelab status, updated every minute"),
        ("alerts", "🚨┃alerts", "Log from Uptime Kuma, Speedtest Tracker and the disk checks (Home Assistant sends "
                               "the phone alerts). Pings only when HA is down, after a crash, or a commit is blocked"),
        ("logs", "📜┃logs", "What the bot and Claude did")]),
    ("control", "── CONTROL ──", [
        ("control", "🎛┃control", "Buttons for the PC, the TV, the light, the PS3 and the PS5"),
        ("claude", "💬┃claude", "Type here to talk to Claude on the PC. /new starts a fresh conversation"),
        ("tv", "📺┃tv", "Paste a YouTube link, share one from your phone, or type a search: it plays on the TV"),
        ("links", "🔗┃links", "Paste a link: it opens in the browser on the PC"),
        ("files", "📁┃files", "Drop files here: they're saved to ~/Downloads/Discord on the PC. /getfile fetches one")]),
    ("personal", "── PERSONAL ──", [
        ("general", "👋┃general", "Chat"),
        ("notes", "📝┃notes", "Notes to self"),
        ("gta6", "🌴┃gta6", "Rockstar Newswire's GTA VI posts, with pictures and videos")]),
]
RADIO_NAME = "📻 Vice Radio"
VOICE = {"gaming": [("party", "🎮 Party"), ("mc_voice", "⛏️ Minecraft")]}  # category -> [(key, voice channel name)]
CREW_ROLE = "Crew"  # Shane gives it to his friend and partner (tap their name › Roles)
CREW_CATEGORIES = ("gaming", "lounge")
PUBLIC_CATEGORIES = ("welcome",)
READ_ONLY = ("online",)  # Crew channels only the bot posts in
CREW_CHANNELS = ("crew_help",)  # opened (read-only) to the Crew inside a section that's otherwise Shane's
PSN_ME = "MyPSNName"  # Shane's PSN account (listed first on #online)
PSN_NAMES = {PSN_ME: "Shane", "FriendPSN1": "Alex", "FriendPSN2": "Sam"}  # PSN name -> what #online shows  # everyone in the server can read these (nobody but Shane and the bot can post)
SWITCH_NAMES: dict[str, str] = {}  # Nintendo nickname -> name on the cards (friends of the bot's Nintendo account)
OLD_CATEGORIES = {"live": "Homelab", "personal": "Personal"}  # adopted by name before categories had keys
THEME = {"green": 0x7EE2A8, "gold": 0xFFC56B, "red": 0xFF8A7A, "accent": 0xC77DBA}  # the lights of the TV home
SERVER_NAME = "Vice City HQ"
BOT_NAME = "VICE"
ABOUT = ("Shane's homelab, on fedora. Watches the PC, the containers and the backups, and says so when "
         "something's wrong. Claude lives in #claude.")
CLAUDE_INTRO = ("Type here and Claude answers, on your Claude plan. It can run commands and change files on fedora, "
                "with the same safety check as your normal chats. A conversation carries on until it has been quiet "
                "for 30 minutes; `/new` starts a fresh one, and `/ask` works in any channel.")
BOSS_ROLE = "Boss"
BOSS_COLOUR = THEME["gold"]  # Shane's pick (2026-11-12): a colour apart from the bot's own accent-coloured role
OLD_BOSS_ROLES = ("👑 Boss",)  # what the role was called before; renamed on sight
ICON = os.path.join(HERE, "assets", "icon.png")  # the bot's avatar: official Beach artwork
SERVER_ICON = os.path.join(HERE, "assets", "server-icon.png")  # the duotone Vice badge (make_badge.py)
BANNER = os.path.join(HERE, "assets", "banner.png")
CONTROL_ART = os.path.join(HERE, "assets", "control.png")
CLAUDE_ART = os.path.join(HERE, "assets", "claude.png")
COMMANDS_ART = os.path.join(HERE, "assets", "commands.png")
STATUS_ART = os.path.join(HERE, "assets", "status.jpg")  # card headers: make_art.py
WELCOME_ART = os.path.join(HERE, "assets", "welcome.png")
CREW_GUIDE_ART = os.path.join(HERE, "assets", "crew-guide.png")
EMOJI_DIR = os.path.join(HERE, "assets", "emoji")
GRAPH_EVERY = 300  # seconds between graph images
URL_RE = re.compile(r"https?://[^\s<>]+")
DEFAULTS = {"Text Channels": {"general"}, "Voice Channels": {"General"}}  # a fresh server's own channels

# /getfile never sends these: anything under a hidden folder or named like a secret (Discord keeps attachments)
SECRET_NAME = re.compile(r"(^|[._-])(token|secrets?|passwords?|credentials?|npsso)([._-]|$)|(^|\.)env$"
                         r"|\.(pem|key|kdbx|p12|pfx|gpg|asc)$|^id_(rsa|ed25519|ecdsa|dsa)", re.I)

log = logging.getLogger("homelab-bot")
discord.VoiceClient.warn_nacl = discord.VoiceClient.warn_dave = False  # no voice here: skip the PyNaCl/davey warnings


def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state: dict):
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=1)
    os.replace(tmp, STATE_FILE)


def webhook(text: str):
    """Post to the homelab Discord webhook from ~/homelab/alerts.env (the same one the disk-health check uses),
    mentioning Shane (DISCORD_MENTION) so it notifies: the server only notifies on @mentions."""
    import urllib.request
    env = {}
    for line in open(os.path.join(HOME, "homelab/alerts.env")):
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    if env.get("DISCORD_WEBHOOK_URL"):
        mention = env.get("DISCORD_MENTION", "")
        req = urllib.request.Request(env["DISCORD_WEBHOOK_URL"],
                                     data=json.dumps({"content": f"{mention} {text}".strip()}).encode(),
                                     headers={"Content-Type": "application/json", "User-Agent": "homelab-bot"})
        urllib.request.urlopen(req, timeout=15)


def containers() -> list[str]:
    """Every Docker container's name, for the Restart… menu. Leaves out the Forgejo runner's short-lived CI job
    containers (FORGEJO-ACTIONS-TASK-…, over 100 characters): Discord refuses menu options that long, and when one
    existed at start-up the #control refresh failed and stopped on_ready (2026-11-14 09:21 and 11:01, after pushes)."""
    code, out = collect._cmd(["docker", "ps", "-a", "--format", "{{.Names}}"], timeout=10)
    return sorted(n for n in out.split() if not n.startswith("FORGEJO-ACTIONS-") and len(n) <= 100) if code == 0 else []


async def run(*args: str, timeout: float = 60) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT, stdin=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return 124, "timed out"
    return proc.returncode, out.decode(errors="replace").strip()


async def save_attachments(attachments: list[discord.Attachment]) -> list[str]:
    """Save a message's attachments to ~/Downloads/Discord without overwriting; returns their full paths."""
    os.makedirs(INBOX, exist_ok=True)
    saved = []
    for a in attachments:
        base, ext = os.path.splitext(os.path.basename(a.filename) or "file")
        path, i = os.path.join(INBOX, base + ext), 1
        while os.path.exists(path):
            path, i = os.path.join(INBOX, f"{base} ({i}){ext}"), i + 1
        await a.save(path)
        saved.append(path)
    return saved


# ---------- errors: say what went wrong instead of leaving "thinking…" up ----------
async def report_error(interaction: discord.Interaction, error: Exception):
    error = getattr(error, "original", error)  # app commands wrap the real error
    if isinstance(error, app_commands.CheckFailure):
        text = "Only Shane can use this."
    else:
        log.error("Interaction failed", exc_info=error)
        text = f"That failed: {type(error).__name__}: {error}"[:1900]
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


async def app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    await report_error(interaction, error)


# ---------- control panel ----------
async def owner_check(bot: HomelabBot, interaction: discord.Interaction) -> bool:
    if interaction.user.id == bot.owner_id:
        return True
    await interaction.response.send_message("Only Shane can use this.", ephemeral=True)
    return False


class OwnerView(discord.ui.View):
    """Buttons only Shane can press; an unexpected error is reported to him."""

    async def interaction_check(self, interaction):
        return await owner_check(interaction.client, interaction)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


def is_crew(interaction: discord.Interaction) -> bool:
    """Shane, or someone with the Crew role (they may use /radio and its buttons; everything else is Shane's)."""
    if interaction.user.id == interaction.client.owner_id:
        return True
    return any(r.name == CREW_ROLE for r in getattr(interaction.user, "roles", []))


class OwnerCard(discord.ui.LayoutView):
    """A card (cards.py) whose buttons only Shane can press; an unexpected error is reported to him."""

    async def interaction_check(self, interaction):
        return await owner_check(interaction.client, interaction)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


# ---------- slash commands (owner only) ----------
def owner_only():
    async def pred(interaction: discord.Interaction):
        return interaction.user.id == interaction.client.owner_id
    return app_commands.check(pred)


LONDON = zoneinfo.ZoneInfo("Europe/London")
