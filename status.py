"""The minute loop: the snapshot of the PC, consoles and TV, the problems handed to Home Assistant, the pinned
#status message and the bot's look; plus the reminder and GTA VI loops."""
from __future__ import annotations

import asyncio
import datetime
import zoneinfo
import io
import json
import os
import re
import time

import discord
from discord.ext import tasks

import cards
import collect
import gaming
import graphs
import gta6
import rockstar_news
import playtime
import wanted

from common import GRAPH_EVERY, HA_STATE, LONDON, PSN_ME, PSN_NAMES, STATUS_ART, SWITCH_NAMES, log, run, save_state, webhook


def gta_card(x: dict) -> cards.Card:
    """A Rockstar Newswire GTA VI post: headline, its text, its pictures (up to 4) and buttons to the post and its
    first video."""
    photos = [p if isinstance(p, str) else p.get("url") or p.get("image") for p in x.get("photos") or []]
    pics = [u for u in dict.fromkeys([x.get("image")] + photos) if u][:4]
    links = [cards.link("Read on Rockstar", x["url"])]
    links += [cards.link("Watch" if i == 0 else f"Video {i + 1}", f"https://www.youtube.com/watch?v={v}", "▶️")
              for i, v in enumerate(x.get("videos", [])[:3])]
    return cards.Card(cards.card(
        "accent",
        cards.text("-# 🌴 ROCKSTAR NEWSWIRE · GTA VI" + (f" · {x['date']}" if x.get("date") else ""),
                   f"## {x['title'][:200]}", x.get("subtitle", "")[:400]),
        cards.pictures(pics) if pics else None,
        cards.row(*links)))


PS5_COVERS = os.path.expanduser("~/homelab/home-assistant/config/www/vice-panel/covers")  # HA's scripts/cover.py


def ps5_cover(game: str) -> str | None:
    """The game's art HA saved for the Hideout panel (covers/ps5-<slug>.png), if there is one. GTA VI's (Rockstar's
    launch art, placed 2026-11-16 for launch day) is found under any spelling PSN might use."""
    slug = re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-")[:60]
    if re.search(r"\b(grand theft auto|gta) ?(vi|6)\b", game, re.I):
        slug = "grand-theft-auto-vi"
    path = os.path.join(PS5_COVERS, f"ps5-{slug}.png")
    return path if slug and os.path.isfile(path) else None


def save_cover(game: str, base: str | None, url: str | None = None):
    """A friend's game Shane hasn't played: keep PSN's cover (via HA), or a Switch game's icon from Nintendo (url),
    as covers/ps5-<slug>.png, 512 px."""
    import io as _io
    import urllib.request
    from PIL import Image
    slug = re.sub(r"[^a-z0-9]+", "-", game.lower()).strip("-")[:60]
    data = None
    if slug and url:
        try:
            data = urllib.request.urlopen(url, timeout=15).read()
        except OSError:
            data = None
    elif slug and base:
        data = gaming.psn_art(base)
    if not data:
        return
    try:
        img = Image.open(_io.BytesIO(data)).convert("RGB")
        img.thumbnail((512, 512))
        img.save(os.path.join(PS5_COVERS, f"ps5-{slug}.png"))
    except Exception as e:  # noqa: BLE001  (a bad image: the card goes without)
        log.warning("Couldn't save the cover for %s: %s", game, e)


def ps5_card(game: str, line: str, art: str | None, live: bool) -> discord.ui.Container:
    # not "on the PS5": a friend may be on a PS4 or PC
    body = cards.text("-# 🎮 PLAYING NOW" if live else "-# 🎮 PLAYED", f"## {game}", line)
    return cards.card("green" if live else "accent",
                      discord.ui.Section(body, accessory=discord.ui.Thumbnail("attachment://cover.png")) if art else body)


def status_card(d: dict) -> discord.ui.Container:
    """The #status card from collect.status_parts: headline with the bot's picture, problems, then PC, Now playing
    and Homelab, the 24-hour graphs and a small footer. The accent bar is the health colour."""
    items = [cards.picture("attachment://status.jpg"), cards.header(d["title"], d["sub"])]
    if d["alert"]:
        items.append(cards.text(d["alert"]))
    for heading, body in d["sections"]:
        items += [cards.divider(), cards.text(f"### {heading}", body)]
    items += [cards.divider(), cards.picture("attachment://graphs.png", "Last 24 hours"),
              cards.text("-# Updates every minute · graphs: last 24 hours")]
    return cards.card(d["colour"], *items)


class StatusMixin:
    _psn_at, _psn_err, _psn_fails = 0.0, None, 0  # PSN is asked hourly (full_snapshot)

    # ---------- every minute: status, and problems handed to Home Assistant ----------
    @tasks.loop(minutes=1)
    async def tick(self):
        s = await asyncio.to_thread(self.full_snapshot)
        self.nohen = self.nohen + 1 if s.get("ps3_up") and not s.get("ps3") else 0  # PS3 on, HEN not enabled
        s["ps3_nohen"] = self.nohen
        await self.heal_radio(s)  # before the HA export: it counts towards the problems
        self.graph_hist.add(s)
        if s.get("ps5_game"):  # one minute of play for /playtime
            await asyncio.to_thread(playtime.add_minute, s["ps5_game"])
        if time.time() - self.graph_at >= GRAPH_EVERY:
            await asyncio.to_thread(self.graph_hist.save)
        # Home Assistant first: the phone alerts mustn't stop when Discord is down
        probs = await self.export_for_ha(s)
        try:
            await self.update_status(s, probs)
        except Exception as e:  # noqa: BLE001 - Discord unreachable; try again next minute
            log.warning("Couldn't update #status: %s: %s", type(e).__name__, e)
        try:
            await self.ps5_post(s)
        except Exception as e:  # noqa: BLE001 - Discord unreachable; the session carries on in state.json
            log.warning("Couldn't post the PS5 game: %s: %s", type(e).__name__, e)
        try:
            await self.whos_on()
        except Exception as e:  # noqa: BLE001 - HA or Discord not answering: next minute
            log.warning("Couldn't update #online: %s: %s", type(e).__name__, e)
        try:
            await self.switch_games()
        except Exception as e:  # noqa: BLE001 - Nintendo or Discord not answering: next minute
            log.warning("Couldn't post the Switch games: %s: %s", type(e).__name__, e)

    # ---------- /remind: due reminders (remind.py), checked every 15 s, kept in state.json ----------
    @tasks.loop(seconds=15)
    async def reminders(self):
        now = time.time()
        due = [r for r in self.state.get("reminders", []) if r["at"] <= now]
        if not due:
            return
        self.state["reminders"] = [r for r in self.state.get("reminders", []) if r["at"] > now]
        save_state(self.state)
        for r in due:
            c = self.guild.get_channel(r["channel"]) if self.guild else None
            set_at = datetime.datetime.fromtimestamp(r["set"], LONDON)
            try:
                if c:  # the mention in the card still notifies
                    await c.send(view=cards.Card(cards.card("gold", cards.text(
                        "-# 🔔 REMINDER", f"## {r['text']}", f"<@{self.owner_id}> · set {set_at.strftime('%a %H:%M')}"))),
                        allowed_mentions=discord.AllowedMentions(users=True))
            except discord.HTTPException as e:
                log.warning("Couldn't post a reminder: %s", e)
            # a Vice OSD card through HA (script.vice_osd): on the TV (over anything) and the Hideout panel
            card = {"title": r["text"], "line": "Reminder", "em": "from the bot",
                    "sub": f"Set {set_at.strftime('%a %H:%M')}", "icon": "bell", "ttl": 15}
            try:
                await asyncio.to_thread(gaming.ha, "/api/services/script/vice_osd?return_response", card, 10)
            except Exception as e:  # noqa: BLE001  (HA or the TV off: Discord has it)
                log.warning("Couldn't send the reminder card to the TV: %s", e)

    # ---------- every 3 hours: GTA VI news (gta6.py) ----------
    @tasks.loop(hours=3)
    async def gta_news(self):
        # Rockstar's own GTA VI posts with photos and videos (rockstar_news.py): the file Hideout Home and the HA panel
        # read, then new posts in #gta6 with their picture, and a pop-up on the TV while it's on
        try:
            items = await asyncio.to_thread(rockstar_news.update)
            log.info("Rockstar GTA VI feed: %d posts", len(items))
            new = await asyncio.to_thread(gta6.new_posts, items)
        except Exception as e:  # noqa: BLE001 - the last good feed stays in place; try again next time
            log.warning("Rockstar GTA VI feed failed: %s: %s", type(e).__name__, e)
            return
        for x in new:
            await self.post("gta6", view=gta_card(x))
            await asyncio.to_thread(self.tv_popup, "GTA VI: " + x["title"][:90])

    @staticmethod
    def tv_popup(text: str):
        try:
            if gaming.ha("/api/states/media_player.lg_tv", timeout=8)["state"] not in ("off", "standby", "unavailable"):
                gaming.ha("/api/services/notify/lg_webos_tv_55qned87a6b_bekfljp", {"message": text}, timeout=15)
        except Exception as e:  # noqa: BLE001 - HA or the TV not answering: the Discord post is enough
            log.warning("TV pop-up failed: %s: %s", type(e).__name__, e)

    @staticmethod
    def full_snapshot() -> dict:
        def ps5():
            state = gaming.ps5_state()
            return state, gaming.ps5_game() if state == "on" else None

        def ps3():
            up = gaming.ps3_reachable()  # a short ping first: webMAN takes 3 s to time out when it's off
            status = gaming.ps3_status() if up else None
            return up, status, gaming.ps3_last_game() if status else None

        # all at the same time as the PC checks (they're mostly waiting on the network: ~5 s in a row, ~2 s together)
        s = collect.snapshot({"ps5": ps5, "ps3": ps3, "nsw": gaming.switch_awake, "streaming": gaming.sunshine_streaming, "tv": gaming.tv_now,
                              "tv_ssh": gaming.tv_ssh_open, "user_units": collect.user_units})
        s["ps5"], s["ps5_game"] = s["ps5"] or ("off", None)
        s["ps3_up"], s["ps3"], s["ps3_game"] = s["ps3"] or (False, None, None)
        s["user_units"] = s["user_units"] or {}
        # PSN is asked once an hour, or 10 minutes after a failure; only 3 failures in a row count (PSN has blips)
        if time.time() - StatusMixin._psn_at > (600 if StatusMixin._psn_fails else 3600):
            err = gaming.psn_error()
            StatusMixin._psn_at = time.time()
            StatusMixin._psn_fails = StatusMixin._psn_fails + 1 if err else 0
            if err:
                log.warning("PSN check failed (%d in a row): %s", StatusMixin._psn_fails, err)
            StatusMixin._psn_err = err if StatusMixin._psn_fails >= 3 else None
        s["psn_error"] = StatusMixin._psn_err
        s["restart"] = collect.restart_needed()
        return s

    async def online_card(self):
        """#online's one card: a PlayStation part (whos_on) and a Switch part (switch_online), each kept in
        state.json, edited only when either changes. Replaced the separate Switch card (2026-11-16)."""
        c = self.ch("online")
        if not c:
            return
        if "switch_online_card" in self.state:  # the old separate Switch card
            try:
                await c.get_partial_message(self.state.pop("switch_online_card")).delete()
            except discord.HTTPException:
                pass
            self.state.pop("switch_online_text", None)
            save_state(self.state)
        psn, sw = self.state.get("online_psn"), self.state.get("online_switch")
        key = f"{psn}\n--\n{sw}"
        if not psn or key == self.state.get("online_text"):
            return
        live = self.state.get("online_psn_live") or self.state.get("online_switch_live")
        view = cards.Card(cards.card("green" if live else "accent",
                                     cards.text("-# 🎮 PLAYSTATION", psn),
                                     *((cards.divider(), cards.text("-# 🕹️ SWITCH", sw)) if sw else ())))
        try:
            await c.get_partial_message(self.state["online_card"]).edit(view=view)
        except (KeyError, discord.NotFound):
            self.state["online_card"] = (await c.send(view=view)).id
        self.state["online_text"] = key
        save_state(self.state)

    async def whos_on(self):
        """#online's PlayStation part: Shane and the PSN friends HA tracks (gaming.psn_friends); and a game card for
        each friend, like Shane's (game_session)."""
        friends = await asyncio.to_thread(gaming.psn_friends)
        e = {**collect.EMOJI, **(self.emoji or {})}
        lines = []
        for f in sorted(friends, key=lambda f: f["name"] != PSN_ME):  # Shane first
            who = f"**{PSN_NAMES.get(f['name'], f['name'])}**"
            if f["game"]:
                lines.append(f"{e['ok']} {who} · playing **{f['game']}**")
            elif f["status"] == "offline":
                last = datetime.datetime.fromisoformat(f["last"]) if f["last"] else None
                lines.append(f"{e['off']} {who} · offline" + (f" · last on <t:{int(last.timestamp())}:R>" if last else ""))
            else:
                lines.append(f"{e['warn' if f['status'] == 'busy' else 'ok']} {who} · "
                             + ("busy" if f["status"] == "busy" else "online"))
        self.state["online_psn"] = "\n".join(lines) or "No PSN friends added yet (HA › PlayStation Network › Add friend)."
        self.state["online_psn_live"] = any(f["game"] or f["status"] != "offline" for f in friends)
        await self.online_card()
        # the Crew's games: the same cards as Shane's (game_session), with the cover PSN shows for their game when
        # Shane hasn't played it (saved where HA keeps his, so the Hideout panel can use it too)
        for f in friends:
            if f["name"] == PSN_ME:
                continue
            if f["game"] and not ps5_cover(f["game"]):
                await asyncio.to_thread(save_cover, f["game"], f.get("base"))
            await self.game_session(PSN_NAMES.get(f["name"], f["name"]), f["game"])

    async def switch_games(self):
        """Switch players (the bot's Nintendo account's friends, gaming.switch_friends): the same game cards as the
        PS5 ones, kept apart from their PSN card (key "<name> (Switch)") so both consoles can run at once."""
        friends = await asyncio.to_thread(gaming.switch_friends)
        if friends is not None:
            await self.switch_online(friends)
        for f in friends or []:
            who = SWITCH_NAMES.get(f["name"], f["name"])
            if f["game"] and not ps5_cover(f["game"]) and f["art"]:
                await asyncio.to_thread(save_cover, f["game"], None, f["art"])
            await self.game_session(who, f["game"], key=f"{who} (Switch)", channel="switch")

    async def switch_online(self, friends: list[dict]):
        """#online's Switch part (online_card): the bot's Nintendo friends, like the PSN lines. Alex isn't on it: he
        has no Switch yet, so he isn't a friend of the bot's account."""
        e = {**collect.EMOJI, **(self.emoji or {})}
        lines = []
        for f in sorted(friends, key=lambda f: SWITCH_NAMES.get(f["name"], f["name"]) != "Shane"):  # Shane first
            who = f"**{SWITCH_NAMES.get(f['name'], f['name'])}**"
            if f["game"]:
                lines.append(f"{e['ok']} {who} · playing **{f['game']}**")
            elif f["status"] == "online":
                lines.append(f"{e['ok']} {who} · online")
            elif f["status"] == "idle":
                lines.append(f"{e['warn']} {who} · idle")
            else:
                lines.append(f"{e['off']} {who} · offline" + (f" · last on <t:{int(f['last'])}:R>" if f["last"] else ""))
        self.state["online_switch"] = "\n".join(lines) or "No Switch friends yet (add the VICE user as a friend on the Switch)."
        self.state["online_switch_live"] = any(f["status"] != "offline" for f in friends)
        await self.online_card()

    async def ps5_post(self, s: dict):
        await self.game_session("Shane", s.get("ps5_game"))

    async def game_session(self, who: str, game: str | None, key: str | None = None, channel: str = "ps5"):
        """A game card per person (Shane from the PS5, the Crew from PSN): when someone starts a game, a card in
        #minecraft (Minecraft) or #ps5-games / #switch-games (the rest) with the cover; when they stop (3 minutes without it, so a
        detection blip doesn't post twice) it says how long they played. Kept in state.json (ps5_sessions)."""
        sessions = self.state.setdefault("ps5_sessions", {})
        if "ps5_session" in self.state:  # before friends had cards too (2026-11-16)
            sessions["Shane"] = self.state.pop("ps5_session")
        self.state.pop("friend_posts", None)  # the one-line "just started" posts' memory, no longer used
        key = key or who
        sess = sessions.get(key)
        if sess and game == sess["game"]:
            if sess.get("missing"):
                sess["missing"] = 0
                save_state(self.state)
            return
        if sess and not game and sess.get("missing", 0) < 2:
            sess["missing"] = sess.get("missing", 0) + 1
            save_state(self.state)
            return
        if sess:  # stopped, or switched to another game
            c = self.guild.get_channel(sess["channel"])
            mins = max(1, round((time.time() - sess["start"]) / 60) - sess.get("missing", 0))
            if c:
                try:
                    await c.get_partial_message(sess["msg"]).edit(view=cards.Card(ps5_card(
                        sess["game"], f"{who} played for {playtime.fmt(mins)} · ended <t:{int(time.time())}:R>",
                        sess.get("cover"), live=False)))
                except discord.HTTPException as e:
                    log.warning("Couldn't update %s's game card: %s", who, e)
            sessions.pop(key, None)
            save_state(self.state)
        if game:
            c = self.ch("minecraft" if "minecraft" in game.lower() else channel)
            if not c:
                return
            art = ps5_cover(game)
            try:
                msg = await c.send(view=cards.Card(ps5_card(game, f"{who} is playing · started <t:{int(time.time())}:R>",
                                                            art, live=True)),
                                   files=[discord.File(art, "cover.png")] if art else [])
            except discord.HTTPException as e:
                return log.warning("Couldn't post %s's game: %s", who, e)
            sessions[key] = {"game": game, "start": time.time(), "channel": c.id, "msg": msg.id, "cover": art}
            save_state(self.state)

    async def heal_radio(self, s: dict):
        """Hideout Radio up but not serving its stream (see collect.radio_stream): after 2 minutes restart the container
        (a restart fixed it every time), at most every 10 minutes; after 5 minutes it's a problem for HA."""
        running = (s.get("containers") or {}).get("radio", ("",))[0] == "running"
        down = getattr(self, "radio_down", 0)
        self.radio_down = s["radio_down"] = down + 1 if running and s.get("radio_stream") is False else 0
        if self.radio_down >= 2 and time.time() - getattr(self, "radio_healed", 0.0) > 600:
            self.radio_healed = time.time()
            log.warning("Hideout Radio isn't serving its stream: restarting the radio container")
            code, out = await run("docker", "restart", "radio", timeout=60)
            try:  # Discord may be the thing that's down: never let the note stop the minute loop
                await self.post("logs", "Hideout Radio wasn't serving its stream: restarted the radio container"
                                + ("" if code == 0 else f" (failed: {out[-200:]})"))
            except Exception as e:  # noqa: BLE001
                log.warning("Couldn't note the radio restart: %s", e)

    @tick.error
    async def tick_error(self, error):
        log.exception("tick failed", exc_info=error)
        self.tick.restart()

    async def update_status(self, s: dict, probs: dict | None = None):
        """Edit the pinned #status message. probs: this minute's problems (else worked out from s)."""
        c = self.ch("status")
        if not c:
            return
        if probs is None:
            probs = collect.problems(s, self.hot_count)
        d = collect.status_parts(s, probs, self.emoji)
        await self.apply_look(d["colour"], d["summary"], s)
        files = []
        if time.time() - self.graph_at >= GRAPH_EVERY:
            png = await asyncio.to_thread(graphs.render, self.graph_hist, s["host"])
            # a message's files are replaced together, so the header (69 KB) goes up with every new graph. Keeping it
            # isn't possible: a card message lists no attachments to keep (they live in its components; tried 2026-11-16)
            files = [discord.File(STATUS_ART, "status.jpg"), discord.File(io.BytesIO(png), "graphs.png")]
        view = cards.Card(status_card(d))
        msg_id = self.state.get("status_card")
        if msg_id:
            try:
                # without attachments= the card keeps its graphs.png until the next one is drawn
                kw = {"attachments": files} if files else {}
                await c.get_partial_message(msg_id).edit(view=view, **kw)
                self.remember_graph(files)
                return
            except discord.NotFound:
                pass
        old = self.state.pop("status_msg", None)  # the embed message from before the cards (2026-11-16)
        if old:
            try:
                await c.get_partial_message(old).delete()
            except discord.HTTPException:
                pass
        if not files:  # a new message needs its own graph image
            png = await asyncio.to_thread(graphs.render, self.graph_hist, s["host"])
            files = [discord.File(STATUS_ART, "status.jpg"), discord.File(io.BytesIO(png), "graphs.png")]
        msg = await c.send(view=view, files=files)
        self.remember_graph(files)
        try:
            await msg.pin()
            async for m in c.history(limit=5):  # drop Discord's "pinned a message" notice
                if m.type == discord.MessageType.pins_add:
                    await m.delete()
        except discord.HTTPException:
            pass
        self.state["status_card"] = msg.id
        save_state(self.state)

    def remember_graph(self, files):
        if files:
            self.graph_at = time.time()

    async def apply_look(self, colour: str, words: str, s: dict | None = None):
        """Bot presence (health colour; activity = what's playing unless something is wrong, else the health words) and the #status channel
        name follow the snapshot (Discord rate-limits renames)."""
        status = {"green": discord.Status.online, "gold": discord.Status.idle}.get(colour, discord.Status.dnd)
        s = s or {}
        tv = s.get("tv") or {}
        if colour != "red" and s.get("ps5_game"):
            act = discord.Game(f"{s['ps5_game']} on PS5")
        elif colour != "red" and s.get("ps3") and s.get("ps3_game") and "PS3" in tv.get("app", ""):
            act = discord.Game(f"{s['ps3_game']} on PS3")
        elif colour != "red" and s.get("streaming"):
            act = discord.Game("on the PC with Moonlight")
        elif colour != "red" and tv.get("power") == "on" and tv.get("app") and tv["app"] not in ("Hideout Home", "Vice Home", "Home Hub", "LG home", "Hearth"):
            act = discord.Activity(type=discord.ActivityType.watching, name=tv["app"] + (f" · {tv['playing']}" if tv.get("playing") else ""))
        elif self.wanted.get("stars"):  # Wanted ★★★ · Container radio is exited
            w = self.wanted
            act = discord.Activity(type=discord.ActivityType.watching,
                                   name=f"Wanted {wanted.stars_text(w['stars'])} · {w['crimes'][0]['what']}"[:120])
        else:
            act = discord.Activity(type=discord.ActivityType.watching, name=f"{collect.platform.node()} · {words}")
        key = (colour, act.name)
        if self.look != key:
            await self.change_presence(status=status, activity=act)
            self.look = key
        c = self.ch("status")
        stars = self.wanted.get("stars", 0)
        want = "⭐" * stars + "┃status" if stars else "📊┃status"  # ⭐⭐⭐┃status (Wanted Level)
        if c and c.name != want and time.time() - self.renamed_at > 330:
            try:
                await c.edit(name=want)
                self.renamed_at = time.time()
            except discord.HTTPException as e:
                log.warning("Couldn't rename #status: %s", e)

    async def export_for_ha(self, s: dict):
        """Alerts and the morning summary moved to Home Assistant (2026-11-11): write the current problems, and
        from 07:55 the morning summary, to a file HA reads every minute (sensor.homelab_state). HA sends the summary
        at 08:00, or as soon as it appears if the bot was down then (until noon). Returns the problems."""
        self.hot_count = self.hot_count + 1 if s["temp"] is not None and s["temp"] >= collect.TEMP_C else 0
        now = collect.problems(s, self.hot_count - 1)
        self.wanted = wanted.update(self.wanted, now, time.time())
        await asyncio.to_thread(wanted.save, self.wanted)
        out = {"updated": time.time(), "problems": now, "morning": self.state.get("morning"),
               "wanted": wanted.for_ha(self.wanted)}
        local = datetime.datetime.now(zoneinfo.ZoneInfo("Europe/London"))
        today = local.date().isoformat()
        if (7, 55) <= (local.hour, local.minute) < (12, 0) and (self.state.get("morning") or {}).get("date") != today:
            text = await asyncio.to_thread(collect.morning_text, s, now)
            self.state["morning"] = out["morning"] = {"date": today, "text": text}
            save_state(self.state)
        tmp = HA_STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(out, f)
        os.replace(tmp, HA_STATE)
        self.problems = now
        if self.wanted.get("change") in ("up", "down", "clear"):  # not "evading": the stars flash, Discord waits
            await self.wanted_card()
        await self.watch_ha()
        return now

    async def wanted_card(self):
        """A card in #alerts when the Wanted Level changes (the quiet log; HA does the phone and the TV)."""
        w = self.wanted
        stars, crimes = w["stars"], w.get("crimes", [])
        if w["change"] == "clear":
            best = max(w.get("best_clean", 0), 0)
            body = ["-# ⭐ WANTED LEVEL", "## Lost them", f"Shook off {wanted.stars_text(w.get('evaded') or 0)}. "
                    "Clean streak starts now" + (f" (record {best / 86400:.1f} days)" if best >= 3600 else "") + "."]
            colour = "green"
        else:
            up = w["change"] == "up"
            # from zero it's a new wanted level; from one or more stars it's heat rising (or dropping)
            what = ("NOW WANTED" if not w.get("was") else "HEAT RISING") if up else "HEAT DROPPING"
            body = [f"-# ⭐ WANTED LEVEL · {what}", f"## {wanted.stars_text(stars)}",
                    *(f"★ {c['what']} · since <t:{int(c['since'])}:R>" for c in crimes[:8]),
                    *(f"✓ Fixed: {f}" for f in w.get("fixed", [])[:5])]
            colour = "red" if stars >= 3 else "gold"
        await self.post("alerts", view=cards.Card(cards.card(colour, cards.text(*body))))

    async def watch_ha(self):
        """HA sends every alert, so it can't report itself being down: if it doesn't answer for 3 minutes, post one
        warning through the homelab Discord webhook (alerts.env), and say when it's back."""
        try:
            await asyncio.to_thread(gaming.ha, "/api/", None, 10)
            self.ha_fails = 0
        except Exception:  # noqa: BLE001
            self.ha_fails = getattr(self, "ha_fails", 0) + 1
        down = self.ha_fails >= 3
        if down != self.state.get("ha_down", False):
            try:
                await asyncio.to_thread(webhook, "Heads up, Shane: Home Assistant isn't answering, so phone alerts are "
                                        "paused. Restart it from #control (Restart… › homeassistant), or check "
                                        "`sudo docker logs homeassistant`" if down else
                                        "Sorted: Home Assistant is answering again; phone alerts are back on.")
            except Exception as e:  # noqa: BLE001 - try again next minute
                return log.warning("Couldn't post the Home Assistant warning: %s", e)
            self.state["ha_down"] = down
            save_state(self.state)
