"""Buttons, menus and pop-up forms: the #control panel and its sub-panels, the phone camera, Claude's Stop,
the /radio card's Skip and Stop."""
from __future__ import annotations

import asyncio
import io
import os
import tempfile

import discord

import claude_chat
import collect
import gaming
import radio

from typing import TYPE_CHECKING
import cards
from common import CREW_ROLE, GOVEE, OwnerCard, OwnerView, PHONE_CAM, PIXEL_KDECONNECT, SUNSHINE, containers, is_crew, owner_check, report_error, run, save_state

if TYPE_CHECKING:
    from bot import HomelabBot


class RadioCard(cards.Card):
    """The /radio now-playing card: song, artist, where it's from, the cover (or the bot's picture), Skip and Stop.
    Skip is the same as on the TV, so it skips there too."""

    def __init__(self, song: dict, thumb: str):
        body = cards.text("-# 📻 VICE RADIO · ON AIR", f"## {song.get('title') or 'Vice Radio'}",
                          song.get("artist") or "", f"-# {radio.source(song)}")
        super().__init__(cards.card(
            "accent", discord.ui.Section(body, accessory=discord.ui.Thumbnail(thumb)),
            cards.row(cards.button("Skip", self.skip, emoji="⏭️"),
                      cards.button("Stop", self.stop_radio, style=cards.Style.danger, emoji="⏹️"))))

    async def interaction_check(self, interaction):  # Shane and the Crew
        if is_crew(interaction):
            return True
        await interaction.response.send_message("Only the Crew can control the radio.", ephemeral=True)
        return False

    async def skip(self, interaction: discord.Interaction):
        if not await asyncio.to_thread(radio.may_skip, interaction.user.id, interaction.client.owner_id):
            return await interaction.response.send_message(radio.SKIP_BLOCKED, ephemeral=True)
        await asyncio.to_thread(radio.skip)
        await interaction.response.send_message("Skipped: the next song starts in a few seconds.", ephemeral=True)

    async def stop_radio(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await interaction.client.radio_stop()


def join_request_card(member: discord.Member, owner_id: int, outcome: str | None = None) -> cards.Card:
    """The request in #logs when someone presses Let me in; outcome replaces the buttons once Shane decides."""
    body = cards.text("-# 🚪 JOIN REQUEST", f"## {member.display_name}",
                      f"{member.mention} · @{member.name} · account made <t:{int(member.created_at.timestamp())}:R>",
                      outcome or f"<@{owner_id}> Approve gives them the Crew role; Deny removes them from the server.")
    tail = None if outcome else cards.row(JoinDecision("ok", member.id), JoinDecision("no", member.id))
    return cards.Card(cards.card("accent" if outcome else "gold",
                                 discord.ui.Section(body, accessory=discord.ui.Thumbnail(member.display_avatar.url)),
                                 tail))


class JoinDecision(discord.ui.DynamicItem[discord.ui.Button], template=r"hb:join:(?P<act>ok|no):(?P<uid>\d+)"):
    """Approve / Deny on a join request. The custom_id carries the decision and the person, so the buttons keep
    working after restarts (setup_hook: add_dynamic_items). Only Shane can press them."""

    def __init__(self, act: str, uid: int):
        super().__init__(discord.ui.Button(
            label="Approve" if act == "ok" else "Deny", custom_id=f"hb:join:{act}:{uid}",
            style=discord.ButtonStyle.success if act == "ok" else discord.ButtonStyle.danger))
        self.act, self.uid = act, uid

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["act"], int(match["uid"]))

    async def interaction_check(self, interaction):
        return await owner_check(interaction.client, interaction)

    async def callback(self, interaction: discord.Interaction):
        bot, g = interaction.client, interaction.guild
        bot.state.setdefault("join_requests", {}).pop(str(self.uid), None)
        save_state(bot.state)
        member = g.get_member(self.uid)
        if not member:
            try:
                member = await g.fetch_member(self.uid)
            except discord.NotFound:
                return await interaction.response.edit_message(view=cards.Card(cards.card("accent", cards.text(
                    "-# 🚪 JOIN REQUEST", "They've already left the server."))))
        if self.act == "ok":
            await member.add_roles(discord.utils.get(g.roles, name=CREW_ROLE), reason="Approved by Shane")
            outcome = "✅ Approved: they're in the Crew."
            try:  # a heads-up, if they accept DMs
                await member.send("You're in! The gaming channels in Vice City HQ are open now.")
            except discord.HTTPException:
                pass
        else:
            await member.kick(reason="Join request denied by Shane")
            outcome = "⛔ Denied: removed from the server."
        await interaction.response.edit_message(view=join_request_card(member, bot.owner_id, outcome))


class WelcomeCard(discord.ui.LayoutView):
    """The card in #welcome, the only thing a newcomer sees. Let me in gives them the Crew role, which opens GAMING
    and LOUNGE (nothing else: the rest of the server stays Shane's). Anyone in the server may press it: only Shane
    makes invites. custom_id hb:join keeps it working after restarts (setup_hook registers this view)."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(cards.card(
            "accent",
            cards.picture("attachment://welcome.png"),
            cards.text("Shane's server for gaming together.",
                       "🎮 **PS5 games** and ⛏️ **Minecraft**: text and voice channels",
                       "📻 **Vice Radio**: an 80s station, played in voice with `/radio`",
                       "-# Press the button to ask Shane to let you into the Crew and its gaming channels."),
            cards.row(cards.button("Let me in", self.join, "hb:join", cards.Style.success, emoji="🎮"))))

    async def join(self, interaction: discord.Interaction):
        crew = discord.utils.get(interaction.guild.roles, name=CREW_ROLE)
        member = interaction.user
        if not crew or not isinstance(member, discord.Member):
            return await interaction.response.send_message("Something's not set up yet: ask Shane.", ephemeral=True)
        if crew in member.roles:
            return await interaction.response.send_message("You're already in: GAMING and LOUNGE are in the "
                                                           "channel list.", ephemeral=True)
        # Shane approves every join (2026-11-16): a request card in #logs that pings him
        bot = interaction.client
        pending = bot.state.setdefault("join_requests", {})
        if str(member.id) in pending:
            return await interaction.response.send_message("Already asked: Shane will let you in shortly.",
                                                           ephemeral=True)
        await interaction.response.send_message("Request sent: Shane will let you in shortly. The gaming "
                                                "channels appear here once he does.", ephemeral=True)
        logs = bot.ch("logs")
        msg = await logs.send(view=join_request_card(member, bot.owner_id),
                              allowed_mentions=discord.AllowedMentions(users=[discord.Object(bot.owner_id)]))
        pending[str(member.id)] = msg.id
        save_state(bot.state)

    async def on_error(self, interaction, error, item):
        await report_error(interaction, error)


LIGHTS = (("On", "on"), ("Off", "off"), ("Warm white", "white 2700"), ("Cool white", "white 6500"), ("Red", "255 0 0"),
          ("Orange", "255 100 0"), ("Green", "0 255 0"), ("Cyan", "0 255 255"), ("Blue", "0 0 255"),
          ("Purple", "150 0 255"), ("Pink", "255 0 150"))


class ControlPanel(OwnerCard):
    """The #control card: its art, then the buttons in groups. custom_ids (hb:...) keep them working after a
    restart (setup_hook registers this view); the Restart... list is read when the bot starts."""

    def __init__(self, bot: HomelabBot, logs_channel: int = 0):
        super().__init__(timeout=None)
        self.bot = bot
        B, S = cards.button, cards.Style
        restart = [("Sunshine (game streaming)", "@sunshine")] + [(c, c) for c in containers()[:24]]
        self.add_item(cards.card(
            "accent",
            cards.picture("attachment://control.png"),
            cards.text("-# Only you can press these. Results land in "
                       + (f"<#{logs_channel}>." if logs_channel else "#logs.")),
            cards.divider(),
            cards.text("### 🖥️ PC"),
            cards.row(B("Screenshot", self.shot, "hb:shot", emoji="📸"), B("Refresh", self.refresh, "hb:refresh", emoji="🔄"),
                      B("Restart", self.restart_pc, "hb:restart", S.danger)),
            cards.text("### 📱 Phone camera"),
            cards.row(B("Cam on", self.cam_on, "hb:cam_on"), B("Mic only", self.mic_on, "hb:mic_on"),
                      B("Off", self.cam_off, "hb:cam_off")),
            cards.text("### 📺 Devices"),
            cards.row(B("TV", self.tv, "hb:tv"), B("PS5", self.ps5, "hb:ps5"), B("PS3", self.ps3, "hb:ps3"),
                      B("Find phone", self.find_phone, "hb:find_phone", emoji="🔔")),
            cards.text("### 💡 Light and services"),
            cards.row(cards.menu("Light: on, off, whites, colours…", LIGHTS, self.light_colour, "hb:light_colour")),
            cards.row(cards.menu("Restart a service…", restart, self.container, "hb:container")),
        ))

    async def act(self, interaction: discord.Interaction, label: str, *args: str, timeout=60):
        """Run one command for a button. label names the action ("Restart Sunshine"); the replies say how it went."""
        await interaction.response.defer(ephemeral=True, thinking=True)
        code, out = await run(*args, timeout=timeout)
        ok = code == 0
        await interaction.followup.send(f"{label}: done." if ok else f"{label}: failed.\n```\n{out[-1500:]}\n```",
                                        ephemeral=True)
        await self.bot.post("logs", f"{label}: done" if ok else f"{label}: failed (exit {code})")

    async def shot(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        with tempfile.TemporaryDirectory() as d:  # spectacle won't overwrite an existing file
            path = os.path.join(d, "screen.png")
            code, out = await run("spectacle", "--background", "--nonotify", "--fullscreen", "--output", path)
            for _ in range(30):
                if os.path.exists(path) and os.path.getsize(path):
                    break
                await asyncio.sleep(0.1)
            if not os.path.exists(path) or not os.path.getsize(path):
                return await interaction.followup.send(f"Screenshot failed: {out[-500:]}", ephemeral=True)
            with open(path, "rb") as f:
                data = f.read()
        await interaction.followup.send(file=discord.File(io.BytesIO(data), "screen.png"), ephemeral=True)

    async def refresh(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        s = await asyncio.to_thread(self.bot.full_snapshot)
        await self.bot.update_status(s)
        await interaction.followup.send("#status updated.", ephemeral=True)

    async def tv(self, interaction):
        now = await asyncio.to_thread(gaming.tv_now)
        line = ("TV: off or not answering." if not now or now["power"] not in ("on", None) else
                f"TV: on, showing {now['app']}" + (f" · {now['playing']}" if now.get("playing") else "") + ".")
        await interaction.response.send_message(line, view=TVPanel(self.bot), ephemeral=True)

    async def ps3(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if not await asyncio.to_thread(gaming.ps3_status):
            on = await asyncio.to_thread(gaming.ps3_reachable)
            return await interaction.followup.send("The PS3 is on but HEN isn't enabled yet." if on else
                                                   "The PS3 is off.", ephemeral=True)
        await interaction.followup.send("PS3: on.", view=PS3Panel(self.bot), ephemeral=True)

    async def light_colour(self, interaction, select: discord.ui.Select):
        name = next(o.label for o in select.options if o.value == select.values[0])
        v = select.values[0].split()
        if v[0] in ("on", "off"):
            return await self.act(interaction, f"Light {v[0]}", GOVEE, v[0])
        if v[0] == "white":
            return await self.act(interaction, name, GOVEE, "white", v[1])
        await self.act(interaction, f"Light colour {name.lower()}", GOVEE, "color", *v)

    async def container(self, interaction, select: discord.ui.Select):
        if select.values[0] == "@sunshine":
            return await self.act(interaction, "Restart Sunshine", "systemctl", "--user", "restart", SUNSHINE)
        if select.values[0] not in await asyncio.to_thread(containers):
            return await interaction.response.send_message(f"There's no container `{select.values[0]}` any more.",
                                                           ephemeral=True)
        await self.act(interaction, f"Restart container `{select.values[0]}`", "docker", "restart",
                       select.values[0], timeout=120)

    async def ps5(self, interaction):
        state = await asyncio.to_thread(gaming.ps5_state)
        await interaction.response.send_message(
            {"on": "PS5: on.", "standby": "PS5: in rest mode.", "off": "PS5: off (not answering)."}[state],
            view=PS5Panel(self.bot), ephemeral=True)

    async def cam_on(self, interaction):
        await start_phone(interaction, self.bot, "front")

    async def mic_on(self, interaction):
        await start_phone(interaction, self.bot, "mic")

    async def cam_off(self, interaction):
        await self.act(interaction, "Stop phone camera", "systemctl", "--user", "stop", "phone-cam-bot")

    async def find_phone(self, interaction):  # KDE Connect rings it even on silent
        await self.act(interaction, "Ring the Pixel", "kdeconnect-cli", "-d", PIXEL_KDECONNECT, "--ring")

    async def restart_pc(self, interaction):
        why = await asyncio.to_thread(collect.restart_needed)
        await interaction.response.send_message(
            ("Restart needed: " + why + ".\n" if why else "No updates are waiting, but you can still restart.\n")
            + "Restart the PC now? Open apps are asked to close first; anything with unsaved work may hold it up. "
            "I'll be back in a few minutes (longer if updates install).", view=ConfirmRestart(self.bot), ephemeral=True)


class StopClaude(OwnerView):
    """The Stop button on the note that follows what Claude is doing."""

    def __init__(self, bot: "HomelabBot", run: claude_chat.Run):
        super().__init__(timeout=claude_chat.TIMEOUT)
        self.bot, self.run = bot, run

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.secondary)
    async def stop(self, interaction, _):
        self.run.stop()
        await interaction.response.edit_message(content="-# Stopping…", view=None)


class TVPanel(OwnerView):
    """Ephemeral living-room TV controls through the couch-tv bridge."""
    def __init__(self, bot: "HomelabBot"):
        super().__init__(timeout=300)
        self.bot = bot

    async def call(self, interaction, path, body, ok):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await asyncio.to_thread(gaming.bridge, path, body)
        except Exception as e:  # noqa: BLE001 - report whatever the bridge said
            return await interaction.followup.send(f"The TV didn't take it: {e}", ephemeral=True)
        await interaction.followup.send(ok, ephemeral=True)
        await self.bot.post("logs", f"TV: {ok}")

    @discord.ui.button(label="Turn on", row=0)
    async def on(self, interaction, _):
        await self.call(interaction, "/api/power", {"state": "on"}, "Turning the TV on.")

    @discord.ui.button(label="Turn off", style=discord.ButtonStyle.danger, row=0)
    async def off(self, interaction, _):
        await self.call(interaction, "/api/power", {"state": "off"}, "TV off.")

    @discord.ui.button(label="Vol −", row=1)
    async def vol_down(self, interaction, _):
        await self.call(interaction, "/api/volume", {"action": "down", "steps": 3}, "Volume down 3.")

    @discord.ui.button(label="Vol +", row=1)
    async def vol_up(self, interaction, _):
        await self.call(interaction, "/api/volume", {"action": "up", "steps": 3}, "Volume up 3.")

    @discord.ui.button(label="Mute", row=1)
    async def mute(self, interaction, _):
        await self.call(interaction, "/api/volume", {"action": "mute"}, "Mute toggled.")

    @discord.ui.select(placeholder="Switch to…", row=2, options=[
        discord.SelectOption(label=n, value=v) for n, v in (
            ("Vice Home", "app.couchtv.home"), ("PS5 (HDMI 1)", "com.webos.app.hdmi1"),
            ("Switch (HDMI 2)", "com.webos.app.hdmi2"), ("Sky Box (HDMI 4)", "com.webos.app.hdmi4"),
            ("YouTube", "youtube.leanback.v4"), ("Netflix", "netflix"), ("Kodi", "org.xbmc.kodi"),
            ("Moonlight", "com.limelight.webos"))])
    async def switch(self, interaction, select: discord.ui.Select):
        name = next(o.label for o in select.options if o.value == select.values[0])
        await self.call(interaction, "/api/launch", {"app": select.values[0]}, f"Switched to {name}.")


class PS5Panel(OwnerView):
    """Ephemeral PS5 controls. Only waking works from here: rest mode and restart need a Remote Play session."""
    def __init__(self, bot: "HomelabBot"):
        super().__init__(timeout=300)
        self.bot = bot

    @discord.ui.button(label="Turn on PS5", style=discord.ButtonStyle.success)
    async def wake(self, interaction, _):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if await asyncio.to_thread(gaming.ps5_state) == "on":
            return await interaction.followup.send("The PS5 is already on.", ephemeral=True)
        try:
            await asyncio.to_thread(gaming.wake_ps5)
        except Exception as e:
            return await interaction.followup.send(f"Couldn't send the wake signal: {e}", ephemeral=True)
        for _ in range(15):
            await asyncio.sleep(2)
            if await asyncio.to_thread(gaming.ps5_state) == "on":
                await interaction.followup.send("PS5 is awake.", ephemeral=True)
                return await self.bot.post("logs", "Wake PS5: done")
        state = await asyncio.to_thread(gaming.ps5_state)
        await interaction.followup.send(
            "The PS5 didn't wake. " + ("It isn't answering at all: it's probably switched off fully or unplugged "
                                          "(waking only works from rest mode)." if state == "off" else
                                          "It's still in rest mode; try again in a moment."), ephemeral=True)



class PS3Panel(OwnerView):
    """Ephemeral PS3 controls through webMAN MOD: restart or shut down (a PS3 can't be woken over the network)."""
    def __init__(self, bot: "HomelabBot"):
        super().__init__(timeout=300)
        self.bot = bot

    async def send(self, interaction, path, ok, log_line):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await asyncio.to_thread(gaming.ps3_cmd, path)
        except OSError as e:
            return await interaction.followup.send(f"The PS3 didn't answer: {e}", ephemeral=True)
        await interaction.followup.send(ok, ephemeral=True)
        await self.bot.post("logs", log_line)

    @discord.ui.button(label="Restart PS3", row=3)
    async def restart(self, interaction, _):
        await self.send(interaction, "/restart.ps3", "Restarting the PS3. Re-enable HEN when it's back.",
                        "PS3: restart")

    @discord.ui.button(label="Shut down PS3", style=discord.ButtonStyle.danger, row=3)
    async def shutdown(self, interaction, _):
        await self.send(interaction, "/shutdown.ps3", "Shutting the PS3 down.", "PS3: shut down")


class ConfirmRestart(OwnerView):
    def __init__(self, bot: "HomelabBot"):
        super().__init__(timeout=60)
        self.bot = bot

    @discord.ui.button(label="Yes, restart", style=discord.ButtonStyle.danger)
    async def yes(self, interaction, _):
        await interaction.response.edit_message(content="Restarting. Back in a few minutes.", view=None)
        await self.bot.post("logs", "Restart PC: requested from #control")
        # KDE's own logout-and-restart closes apps cleanly; without a desktop session, a plain reboot
        code, out = await run("qdbus", "org.kde.Shutdown", "/Shutdown", "org.kde.Shutdown.logoutAndReboot",
                              timeout=20)
        if code != 0:
            code, out = await run("systemctl", "reboot", timeout=20)
        if code != 0:
            await interaction.followup.send(f"Couldn't restart: {out[-500:]}", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def no(self, interaction, _):
        await interaction.response.edit_message(content="Not restarting.", view=None)


# ---------- phone camera: find the phone, ask for the new wireless-debugging port if needed ----------
PORT_FILE = os.path.expanduser("~/.config/phone-cam-port")
PHONE_IPS = ("192.168.0.158",)  # the Pixel, reserved in the router (device MAC 00:00:00:00:00:00)


def saved_port() -> str:
    try:
        with open(PORT_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


async def connect_phone(port: str) -> str | None:
    """adb connect on the given port at each known address; returns the address that worked."""
    if not port.isdigit():
        return None
    for ip in PHONE_IPS:
        code, out = await run("adb", "connect", f"{ip}:{port}", timeout=6)
        if "connected to" in out:
            with open(PORT_FILE, "w") as f:
                f.write(port + "\n")
            return ip
    return None


async def launch_phone(interaction: discord.Interaction, bot: "HomelabBot", mode: str, ip: str):
    code, _ = await run("systemctl", "--user", "is-active", "--quiet", "phone-cam-bot")
    if code == 0:
        return await interaction.followup.send("Already running. Press **Phone cam off** first to switch.",
                                               ephemeral=True)
    what = "Phone mic" if mode == "mic" else "Phone camera"
    code, out = await run("systemd-run", "--user", "--collect", "--unit=phone-cam-bot",
                          f"--setenv=PHONE_IP={ip}", PHONE_CAM, mode)
    if code == 0:
        await asyncio.sleep(6)  # phone-cam exits quickly if something's wrong
        code, _ = await run("systemctl", "--user", "is-active", "--quiet", "phone-cam-bot")
        if code != 0:
            _, out = await run("journalctl", "--user", "-u", "phone-cam-bot", "-n", "8", "--no-pager", "-o", "cat")
    ok = code == 0
    await interaction.followup.send(f"{what} on ({ip})." if ok else f"{what} didn't start:\n```\n{out[-1500:]}\n```",
                                    ephemeral=True)
    await bot.post("logs", f"{what}: {'started' if ok else 'failed to start'}")


async def start_phone(interaction: discord.Interaction, bot: "HomelabBot", mode: str):
    await interaction.response.defer(ephemeral=True, thinking=True)
    ip = await connect_phone(saved_port())
    if ip:
        return await launch_phone(interaction, bot, mode, ip)
    await interaction.followup.send(
        "Can't reach the phone on the last port. On the phone: **Settings › System › Developer options › "
        "Wireless debugging** (turn it on), then press the button and type the number after the colon under "
        "*IP address & Port*.", view=PortPrompt(bot, mode), ephemeral=True)


class PortModal(discord.ui.Modal, title="Phone wireless-debugging port"):
    port = discord.ui.TextInput(label="Port (the number after the colon)", placeholder="e.g. 41235",
                                min_length=4, max_length=5)

    def __init__(self, bot: "HomelabBot", mode: str):
        super().__init__()
        self.bot, self.mode = bot, mode

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        ip = await connect_phone(self.port.value.strip())
        if not ip:
            return await interaction.followup.send(
                f"Couldn't connect on port {self.port.value}. Check the number on the phone (it changes every time "
                "Wireless debugging is turned on) and try again. If the phone asks to pair, run `phone-cam` on the PC "
                "once.", view=PortPrompt(self.bot, self.mode), ephemeral=True)
        await launch_phone(interaction, self.bot, self.mode, ip)

    async def on_error(self, interaction, error):
        await report_error(interaction, error)


class PortPrompt(OwnerView):
    def __init__(self, bot: "HomelabBot", mode: str):
        super().__init__(timeout=600)
        self.bot, self.mode = bot, mode

    @discord.ui.button(label="Enter port", style=discord.ButtonStyle.primary)
    async def enter(self, interaction, _):
        await interaction.response.send_modal(PortModal(self.bot, self.mode))
