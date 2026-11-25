"""/radio: Hideout Radio in a voice channel, with a now-playing card (radio.py has the station side)."""
from __future__ import annotations

import asyncio
import time

import discord
from discord.ext import tasks

import radio

from common import RADIO_NAME, log, save_state
from views import RadioCard


class RadioMixin:

    # ---------- /radio: Hideout Radio in a voice channel (radio.py) ----------
    async def radio_channel(self) -> discord.VoiceChannel:
        """The Hideout Radio voice channel in Lounge (private like the rest), made the first time it's needed."""
        chans = self.state.setdefault("channels", {})
        c = self.guild.get_channel(chans.get("radio", 0))
        if not c:
            cat = self.guild.get_channel(self.state.get("categories", {}).get("lounge", 0))
            over = dict(cat.overwrites) if cat else {}
            over[self.guild.me] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True,
                                                              send_messages=True, embed_links=True, attach_files=True)
            c = await self.guild.create_voice_channel(RADIO_NAME, category=cat, overwrites=over)
            chans["radio"] = c.id
            save_state(self.state)
        if c.bitrate < self.guild.bitrate_limit:  # the most the server allows (96 kbps unboosted; default 64)
            await c.edit(bitrate=int(self.guild.bitrate_limit))
        return c

    async def radio_start(self, channel: discord.VoiceChannel):
        vc = self.guild.voice_client
        if vc and vc.channel != channel:
            old = vc.channel
            await vc.move_to(channel)
            async with self.radio_lock:
                await self.radio_cleanup(old)  # a fresh card in the new channel's chat
        elif not vc:
            vc = await channel.connect(self_deaf=True)
            async with self.radio_lock:
                await self.radio_cleanup(channel)  # leftovers, e.g. from before a bot restart
        if not vc.is_playing():
            self.radio_play(vc)
        self.radio_song = None
        self.radio_empty_since = None
        # restart: a stop() moments ago leaves the loop running until its next tick, then it would end
        self.radio_tick.restart() if self.radio_tick.is_running() else self.radio_tick.start()
        await self.radio_card()

    def radio_play(self, vc: discord.VoiceClient):
        # 128 kbps in Opus's music mode, no loss protection (discord.py's default -fec with 15% packet loss spends bits
        # on redundancy; later ffmpeg options win, so these override it). Shane's ear decides: this "sounds much
        # better" (2026-11-16); the lossless FLAC mount at 256 kbps with soxr sounded worse in Discord.
        # ffmpeg reconnects by itself if the stream blips (a radio container restart takes longer: see radio_ended).
        src = discord.FFmpegOpusAudio(radio.STREAM, bitrate=128,
                                      before_options="-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
                                      options="-application audio -fec false -packet_loss 0")
        vc.play(src, after=lambda err: self.loop.call_soon_threadsafe(self.radio_ended, vc, err))

    def radio_ended(self, vc: discord.VoiceClient, err: Exception | None):
        """The stream stopped while still in the channel (radio container restarted?): try again in 10 s."""
        if not vc.is_connected():
            return  # /radio stop
        log.warning("Hideout Radio stream ended (%s), restarting it in 10 s", err or "no error")
        self.loop.call_later(10, lambda: vc.is_connected() and not vc.is_playing() and self.radio_play(vc))

    async def radio_stop(self, why: str = "Stopped"):
        """Leave the voice channel and clear the bot's messages from its chat (2026-11-16, Shane's ask)."""
        vc = self.guild.voice_client if self.guild else None
        channel = vc.channel if vc else self.radio_msg.channel if self.radio_msg else None
        if vc:
            await vc.disconnect()
        log.info("Hideout Radio off: %s", why)
        self.radio_tick.stop()  # not cancel(): this runs inside the loop too, and the cleanup below must finish
        if channel:
            async with self.radio_lock:
                await self.radio_cleanup(channel)

    async def radio_cleanup(self, channel: discord.abc.Messageable):
        """Delete the bot's own messages in a voice channel's chat: its now-playing cards, old ones included."""
        self.radio_msg, self.radio_song = None, None
        try:
            await channel.edit(status=None)  # the song under the channel name goes too
        except discord.HTTPException:
            pass
        try:
            async for m in channel.history(limit=50):
                if m.author == self.user:
                    await m.delete()
        except discord.HTTPException as e:
            log.warning("Couldn't clear the Hideout Radio messages: %s", e)

    async def radio_card(self):
        """Post the now-playing card in the voice channel's chat, or edit it when the song changes. One at a time:
        the start and the loop's first tick both called this and each posted a card (duplicates, 2026-11-16)."""
        async with self.radio_lock:
            await self._radio_card()

    async def _radio_card(self):
        vc = self.guild.voice_client
        if not vc or not vc.is_connected():
            return
        try:
            song = await asyncio.to_thread(radio.now)
        except Exception as e:  # noqa: BLE001  (radio container down: the card waits)
            log.warning("Hideout Radio now-playing failed: %s", e)
            return
        key = (song.get("artist"), song.get("title"), song.get("station"))
        if key == self.radio_song and self.radio_msg:
            return
        self.radio_song = key
        # the song under the voice channel's name too, so people in voice see it without opening the chat
        title = " · ".join(x for x in (song.get("title"), song.get("artist")) if x) or "Hideout Radio"
        try:
            await vc.channel.edit(status=f"📻 {title}"[:500])
        except discord.HTTPException as e:
            log.warning("Couldn't set the voice channel status: %s", e)
        art = radio.cover(song)
        files = [discord.File(art, "cover.jpg")] if art else []
        view = RadioCard(song, "attachment://cover.jpg" if art else self.user.display_avatar.url)
        if self.radio_msg:
            try:
                await self.radio_msg.edit(view=view, attachments=files)
                return
            except discord.NotFound:
                pass
        self.radio_msg = await vc.channel.send(view=view, files=files)

    @tasks.loop(seconds=10)
    async def radio_tick(self):
        vc = self.guild.voice_client if self.guild else None
        if not vc or not vc.is_connected():
            await self.radio_stop("Disconnected")
            return
        if any(not m.bot for m in vc.channel.members):
            self.radio_empty_since = None
        elif not self.radio_empty_since:
            self.radio_empty_since = time.time()
        elif time.time() - self.radio_empty_since > 40:  # leaves 40-50 s after the last person (ticks are 10 s)
            await self.radio_stop("Nobody was listening, so it stopped")
            return
        await self.radio_card()
