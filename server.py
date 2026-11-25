"""Building and dressing the server: channels and categories (LAYOUT), icon, banner, roles, emoji, the
headers in #control and #claude, and the pinned guide in #commands."""
from __future__ import annotations

import os

import discord


from common import ABOUT, BANNER, BOSS_COLOUR, BOSS_ROLE, BOT_NAME, CLAUDE_ART, CLAUDE_INTRO, COMMANDS_ART, CONTROL_ART, CREW_CATEGORIES, CREW_CHANNELS, CREW_GUIDE_ART, CREW_ROLE, DEFAULTS, EMOJI_DIR, ICON, LAYOUT, OLD_BOSS_ROLES, OLD_CATEGORIES, PUBLIC_CATEGORIES, RADIO_NAME, READ_ONLY, SERVER_ICON, SERVER_NAME, THEME, VOICE, WELCOME_ART, log, save_state
import cards
from views import ControlPanel, WelcomeCard


class ServerMixin:

    def ch(self, name: str) -> discord.TextChannel | None:
        return self.guild.get_channel(self.state.get("channels", {}).get(name, 0)) if self.guild else None

    async def build_server(self):
        g = self.guild
        owner = g.get_member(self.owner_id) or await g.fetch_member(self.owner_id)
        private = {g.default_role: discord.PermissionOverwrite(view_channel=False),
                   owner: discord.PermissionOverwrite(view_channel=True),
                   g.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True,
                                                     embed_links=True, attach_files=True, read_message_history=True)}
        crew = await self.crew_role()
        # what the Crew may do in GAMING and LOUNGE (the rest of the server stays hidden from them)
        crew_ok = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True,
                                              embed_links=True, attach_files=True, add_reactions=True,
                                              use_application_commands=True, connect=True, speak=True,
                                              use_voice_activation=True, stream=True)
        crew_read = discord.PermissionOverwrite(**{**dict(crew_ok), "send_messages": False, "add_reactions": False,
                                                   "create_public_threads": False, "create_private_threads": False})
        # WELCOME: anyone in the server may read it and press its button, nobody else may post
        read_only = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=False,
                                                add_reactions=False, create_public_threads=False,
                                                create_private_threads=False, send_messages_in_threads=False)
        chans = self.state.setdefault("channels", {})
        cats = self.state.setdefault("categories", {})
        created = []
        placed = []  # (category, its channels) in LAYOUT order
        for cat_key, cat_name, channels in LAYOUT:
            cat = (g.get_channel(cats.get(cat_key, 0)) or discord.utils.get(g.categories, name=cat_name)
                   or discord.utils.get(g.categories, name=OLD_CATEGORIES.get(cat_key))
                   or await g.create_category(cat_name, overwrites=private))
            cats[cat_key] = cat.id
            open_to_crew = cat_key in CREW_CATEGORIES
            if open_to_crew and cat.overwrites_for(crew) != crew_ok:
                await cat.set_permissions(crew, overwrite=crew_ok, reason="Crew can see gaming and the radio")
            if cat_key in PUBLIC_CATEGORIES and cat.overwrites_for(g.default_role) != read_only:
                await cat.set_permissions(g.default_role, overwrite=read_only, reason="Newcomers can read the welcome")
            if cat.name != cat_name:
                await cat.edit(name=cat_name)
            want = []  # this category's channels in LAYOUT order
            for key, name, topic in channels:
                c = g.get_channel(chans.get(key, 0))
                if not c:
                    c = await g.create_text_channel(name, category=cat, topic=topic)
                    chans[key] = c.id
                    created.append(key)
                # #status's name follows the health afterwards (apply_look), so only its topic is kept here
                elif c.topic != topic or (c.name != name and key != "status"):
                    await c.edit(name=name, topic=topic)
                if key in CREW_CHANNELS and c.overwrites_for(crew) != crew_read:
                    await c.set_permissions(crew, overwrite=crew_read, reason="The Crew's guide")
                want.append(c)
            for key, name in VOICE.get(cat_key, []):
                c = g.get_channel(chans.get(key, 0))
                if not c:
                    c = await g.create_voice_channel(name, category=cat, bitrate=int(g.bitrate_limit))
                    chans[key] = c.id
                    created.append(key)
                elif c.name != name:
                    await c.edit(name=name)
                want.append(c)
            radio_ch = g.get_channel(chans.get("radio", 0))
            if cat_key == "lounge" and radio_ch:
                if radio_ch.name != RADIO_NAME:
                    await radio_ch.edit(name=RADIO_NAME)
                want.append(radio_ch)
            if open_to_crew:  # channels with their own overwrites (the radio's) don't follow the category
                read_only_ids = {chans.get(k) for k in READ_ONLY}
                for c in want:
                    ok = crew_read if c.id in read_only_ids else crew_ok
                    if c.overwrites_for(crew) != ok:
                        await c.set_permissions(crew, overwrite=ok, reason="Crew can see gaming and the radio")
            placed.append((cat, want))
        # regroup and reorder in one bulk call, only when something is out of place (move() per channel works from
        # a cache that lags behind its own earlier moves)
        ids = {cat.id for cat, _ in placed}
        if [c.id for c in g.categories if c.id in ids] != [cat.id for cat, _ in placed] or any(
                [c.id for c in cat.channels] != [c.id for c in want] for cat, want in placed):
            await self.http.bulk_channel_update(g.id, [{"id": cat.id, "position": i} for i, (cat, _) in enumerate(placed)])
            for cat, want in placed:  # Discord allows one category change per call
                for c in want:
                    if c.category_id != cat.id:
                        await c.edit(category=cat, sync_permissions=False)
            await self.http.bulk_channel_update(g.id, [
                {"id": c.id, "position": i} for i, c in enumerate(c for _, want in placed for c in want)])
        # empty leftovers with a layout name (a start that failed half-way made duplicates, 2026-11-16)
        names = {n for _, n, _ in LAYOUT} | set(OLD_CATEGORIES.values())
        for c in list(g.categories):
            if c.id not in ids and c.name in names and not c.channels:
                await c.delete(reason="Duplicate category")
        # remove a fresh server's default channels, but only untouched defaults
        for cat_name, names in DEFAULTS.items():
            cat = discord.utils.get(g.categories, name=cat_name)
            if cat and {c.name for c in cat.channels} <= names:
                for c in cat.channels:
                    if not isinstance(c, discord.TextChannel) or not [
                            m async for m in c.history(limit=50) if not m.is_system()]:  # only join notices
                        await c.delete(reason="Clean homelab server")
                if not cat.channels:
                    await cat.delete(reason="Clean homelab server")
        save_state(self.state)
        if created:
            log.info("Created channels: %s", ", ".join(created))
        await self.ensure_header("control", CONTROL_ART, ControlPanel(self, chans.get("logs", 0)))
        await self.ensure_header("claude", CLAUDE_ART, cards.Card(cards.card(
            "accent", cards.picture("attachment://claude.png"),
            cards.text(CLAUDE_INTRO))))
        await self.ensure_header("commands", COMMANDS_ART, cards.Card(self.guide_card()), old="guide_card")
        await self.ensure_header("welcome", WELCOME_ART, WelcomeCard())
        await self.ensure_header("crew_help", CREW_GUIDE_ART, cards.Card(self.crew_guide_card()))

    def guide_card(self) -> discord.ui.Container:
        ch = lambda k: f"<#{self.state.get('channels', {}).get(k, 0)}>"
        return cards.card(
            "accent",
            cards.picture("attachment://commands.png"),
            cards.text("-# Only you can use these. Replies are private unless they say otherwise."),
            cards.divider(),
            cards.text("### 🖥️ The PC",
                       "`/getfile` get a file (browse folders or type a path, up to 10 MB)",
                       "`/clip` see the PC's clipboard · **Apps › Copy to PC clipboard** on any message puts it there",
                       "`/type` type text into whatever has focus (Enter optional)",
                       f"{ch('files')} drop a file to save it to ~/Downloads/Discord · {ch('links')} paste a link to "
                       "open it on the PC"),
            cards.text("### 💬 Claude",
                       f"{ch('claude')} type to talk to Claude on the PC (images and files too)",
                       "`/ask` the same from any channel · `/new` start a fresh conversation"),
            cards.text("### 📺 TV, consoles and music",
                       f"{ch('control')} buttons for the PC, phone camera, TV, PS5, PS3, the light and restarting a "
                       "service",
                       f"{ch('tv')} paste or share a YouTube link, or type a search, to play it on the TV",
                       "`/playtime` PS5 play time this week · `/radio` Hideout Radio in a voice channel",
                       f"**The Crew** (Alex, Sam): newcomers see only {ch('welcome')}; **Let me in** sends you a "
                       f"request in {ch('logs')} to approve. The Crew sees GAMING, LOUNGE and {ch('crew_help')}, "
                       "and can use `/radio`",
                       f"{ch('online')} who's on PSN and Switch · {ch('ps5')} {ch('switch')} {ch('minecraft')} a game card for anyone who "
                       f"starts a game · {ch('crew_general')} chat with the Crew"),
            cards.text("### 📝 Notes and reminders",
                       f"`/note` or type in {ch('notes')}: also saved to ~/Documents/notes.md",
                       "`/remind` remind me here and on the TV (30m, 2h, 18:00…) · `/reminders` see or cancel them"),
            cards.text("### 📊 Keeping watch",
                       f"{ch('status')} live status every minute · {ch('logs')} what was done · {ch('alerts')} log of "
                       "Uptime Kuma, Speedtest and disk checks (pings only when Home Assistant is down, after a crash, "
                       "or a commit is blocked)",
                       f"{ch('gta6')} Rockstar's GTA VI posts · phone alerts, the morning summary, Game night and "
                       "Night are in Home Assistant"),
            cards.divider(),
            cards.text("-# `/cleanup` clears recent messages in a channel · `/setup` rebuilds anything missing"))

    async def brand(self):
        """Bot name, avatar, banner, About Me, and the server's name and icon. Re-applied when any changes."""
        version = [BOT_NAME, ABOUT, SERVER_NAME] + [os.path.getmtime(p) for p in (ICON, BANNER, SERVER_ICON)]
        if self.state.get("brand_version") == version:
            return
        icon, banner, server_icon = (open(p, "rb").read() for p in (ICON, BANNER, SERVER_ICON))
        steps = [("avatar & banner", self.user.edit(avatar=icon, banner=banner)),
                 ("name", self.user.edit(username=BOT_NAME) if self.user.name != BOT_NAME else None),
                 ("About Me", self.about_me()),
                 ("server name and icon", self.guild.edit(name=SERVER_NAME, icon=server_icon))]
        done = True
        for what, coro in steps:
            if coro is None:
                continue
            try:
                await coro
            except discord.HTTPException as e:
                done = False
                log.warning("Couldn't set the %s: %s", what, e)
        if done:
            self.state["brand_version"] = version
            save_state(self.state)

    async def quiet_notifications(self):
        """Server default: notify on @mentions only, so alerts ping but routine log lines don't."""
        if self.guild.default_notifications != discord.NotificationLevel.only_mentions:
            await self.guild.edit(default_notifications=discord.NotificationLevel.only_mentions)
        # Locked by default (2026-11-16, before friends join): @everyone sees no channel unless the channel opens it
        # (GAMING and LOUNGE open to the Crew role), can't ping everyone, and can't make invites (the owner can).
        everyone = self.guild.default_role
        locked = discord.Permissions(everyone.permissions.value)
        locked.update(view_channel=False, mention_everyone=False, create_instant_invite=False)
        if everyone.permissions != locked:
            await everyone.edit(permissions=locked, reason="Locked by default: channels open only to the roles they name")
        if self.guild.verification_level < discord.VerificationLevel.low:  # joiners need a verified email
            await self.guild.edit(verification_level=discord.VerificationLevel.low)
        # #welcome is the server's main channel: Discord's "X joined" notes land there (and its welcome block, once
        # above #status), with every other system notice and the setup tips off
        welcome = self.ch("welcome")
        flags = discord.SystemChannelFlags(**{f: f == "join_notifications" for f, _ in discord.SystemChannelFlags()})
        if welcome and (self.guild.system_channel != welcome or self.guild.system_channel_flags != flags):
            await self.guild.edit(system_channel=welcome, system_channel_flags=flags)

    async def about_me(self):
        app = await self.application_info()
        await app.edit(description=ABOUT)

    async def crew_role(self) -> discord.Role:
        """The role for Shane's friend and partner: it opens GAMING and LOUNGE, nothing else. Shane hands it out."""
        g = self.guild
        role = discord.utils.get(g.roles, name=CREW_ROLE)
        if not role:
            role = await g.create_role(name=CREW_ROLE, colour=discord.Colour(THEME["green"]), hoist=True,
                                       mentionable=True, reason="Gaming with friends")
        # the bot can only hand out roles below its own: keep Crew there (they once shared position 1, 2026-11-16)
        if role >= g.me.top_role:
            await role.edit(position=max(1, g.me.top_role.position - 1), reason="Crew below the bot's role")
        return role

    async def boss_role(self):
        g = self.guild
        owner = g.get_member(self.owner_id) or await g.fetch_member(self.owner_id)
        colour = discord.Colour(BOSS_COLOUR)
        role = next((r for r in g.roles if r.name in (BOSS_ROLE, *OLD_BOSS_ROLES)), None)
        if not role:
            role = await g.create_role(name=BOSS_ROLE, colour=colour, hoist=True, reason="Server look")
        elif role >= g.me.top_role:  # Discord only lets a bot change roles below its own
            if role.name != BOSS_ROLE or role.colour != colour:
                log.info("The %s role is above the bot's own, so the bot can't restyle it. Rename it %s (colour "
                         "#%06X) in Server Settings > Roles, or drag the bot's role above it and restart the bot.",
                         role.name, BOSS_ROLE, BOSS_COLOUR)
            return
        elif role.name != BOSS_ROLE or role.colour != colour:
            await role.edit(name=BOSS_ROLE, colour=colour, reason="Server look")
        if role not in owner.roles:
            await owner.add_roles(role, reason="Server look")

    async def load_emojis(self):
        """Upload the status lights (once), use them in #status and remove the previous look's set."""
        if not os.path.isdir(EMOJI_DIR):
            return
        have = {e.name: e for e in self.guild.emojis}
        for f in sorted(os.listdir(EMOJI_DIR)):
            name = f.removesuffix(".png")
            if name not in have:
                try:
                    with open(os.path.join(EMOJI_DIR, f), "rb") as fh:
                        have[name] = await self.guild.create_custom_emoji(name=name, image=fh.read(),
                                                                          reason="Server look")
                except discord.HTTPException as e:
                    log.warning("Couldn't add emoji %s: %s", name, e)
                    continue
        self.emoji = {k.removeprefix("v_"): str(e) for k, e in have.items() if k.startswith("v_")}
        for name, old in have.items():
            if name.startswith("vc_"):  # the neon set from the previous look
                try:
                    await old.delete(reason="Replaced by the new status lights")
                except discord.HTTPException as e:
                    log.warning("Couldn't remove emoji %s: %s", name, e)

    def crew_guide_card(self) -> discord.ui.Container:
        """#crew-guide: what the Crew can do (the owner's own guide is #commands)."""
        ch = lambda k: f"<#{self.state.get('channels', {}).get(k, 0)}>"
        return cards.card(
            "accent",
            cards.picture("attachment://crew-guide.png"),
            cards.text("-# Everything you can do here. Shane runs the server and the Hideout bot."),
            cards.divider(),
            cards.text("### 🎮 Gaming",
                       f"{ch('online')} who's on PSN and Switch right now and what they're playing",
                       f"{ch('ps5')} · {ch('switch')} · {ch('minecraft')} chat; when anyone starts a game, a card shows up in the "
                       "game's channel and says how long they played when they stop",
                       f"{ch('party')} · {ch('mc_voice')} voice channels for playing together"),
            cards.text("### 📻 Hideout Radio",
                       "`/radio` plays Shane's 80s station in the voice channel you're in "
                       f"(or in {ch('radio')}); the song shows under the channel's name",
                       "`/radio` › **Skip** or **Stop**, or the buttons on the radio card in the voice chat. "
                       "Skip waits while Shane's TV is playing the radio too"),
            cards.text("### 💬 Chat", f"{ch('crew_general')} for everything else"),
            cards.divider(),
            cards.text("-# Tips: long-press the server › Notification Settings › All Messages so you don't miss chat. "
                       "To show up in #online: PS5 › Settings › Users and Accounts › Privacy › Online Status and Now "
                       "Playing › Friends."))

    async def ensure_header(self, key: str, art: str, view: discord.ui.LayoutView, old: str | None = None):
        """The card at the top of #control and #claude (its art is attachment://<art's file name>). Sent once, then
        edited on every start, so text and buttons stay current; the art is uploaded again only when the file changed.
        Never stops start-up: Discord twice refused this at start-up (2026-11-14: a 112-character CI container name in
        the Restart… menu) and on_ready stopped there, so the minute loop (#status, the problems for HA) never
        started. If anything is refused: log what was sent and carry on."""
        c = self.ch(key)
        if not c:
            return
        name = os.path.basename(art)
        stamp = os.path.getmtime(art)
        try:
            try:
                msg = c.get_partial_message(self.state[f"{key}_card"])
                if self.state.get(f"{key}_card_art") != stamp:
                    await msg.edit(view=view, attachments=[discord.File(art, name)])
                    self.state[f"{key}_card_art"] = stamp
                    save_state(self.state)
                else:
                    await msg.edit(view=view)
                return
            except (KeyError, discord.NotFound):
                pass
            # the message this one replaces: the embed header from before the cards (2026-11-16), or `old`
            gone = self.state.pop(old or f"{key}_msg", None)
            if gone:
                try:
                    await c.get_partial_message(gone).delete()
                except discord.HTTPException:
                    pass
            msg = await c.send(view=view, file=discord.File(art, name))
            self.state[f"{key}_card"], self.state[f"{key}_card_art"] = msg.id, stamp
            save_state(self.state)
        except discord.HTTPException as e:
            log.warning("Couldn't put up the #%s card: %s; sent %s", key, e, view.to_components())

    async def post(self, channel: str, text: str = None, **kw):
        c = self.ch(channel)
        if c:
            try:
                return await c.send(text, **kw)
            except discord.HTTPException as e:
                log.warning("Couldn't post to #%s: %s", channel, e)
