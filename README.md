# 🤖 Hideout Bot

<img src="https://raw.githubusercontent.com/ShaneRunham/ShaneRunham/main/screens/hideout-bot/status-card.jpg" alt="The live #status card, updated every minute, with 24-hour graphs" width="40%" align="right">

A Discord bot for my homelab and my friends (its server is **The Hideout**), written in Python with [discord.py](https://github.com/Rapptz/discord.py)
and Discord's Components v2 cards. It's the part of the homelab that notices things: every minute it takes a
snapshot of the PC, the containers, the consoles and the TV, works out what's wrong, and hands that to Home Assistant
for the phone and TV alerts.

**Contents:** [Channels](#channels) · [Wanted Level](#wanted-level) · [Slash commands](#slash-commands) ·
[Friends and gaming](#friends-and-gaming) · [Claude](#claude) · [Files](#files)

## Channels

The bot builds and keeps the server's layout itself (`common.py` `LAYOUT`): categories, channels, icons and who can see them.

| | |
|---|---|
| **#status** | One pinned card, updated every minute: CPU, memory, swap, temperature, disks, internet speed, containers, uptime monitors, Tailscale devices, what's playing (TV, PS5, Switch, Moonlight), the last backup and nightly jobs, and 24-hour graphs. The channel's name shows the Wanted stars (`⭐⭐┃status`) |
| **#alerts** | The quiet log: Wanted Level cards, uptime monitors, speed tests and disk checks. Mentions only for what Home Assistant can't send (HA itself down, a crash, the outside watchdog) |
| **#control** | Buttons: screenshot, refresh, restart the PC, phone camera, find my phone, the light, restart any container, TV (power, volume, input, apps), PS5 |
| **#claude** | Type and Claude answers, with images and files (below) |
| **#tv** | Post a YouTube link or a search and it plays on the TV |
| **#gta6** | Rockstar Newswire's GTA VI posts, with pictures and videos |
| **#files**, **#links**, **#notes** | Drop a file to save it on the PC, a link to open it there, a note to keep it |
| **Hideout Radio** voice channel | The radio, played by the bot |
| **#commands** | A pinned guide to all of it, rewritten on every start |

## Wanted Level

`wanted.py` turns the problems into 0 to 5 stars:

- each problem is worth 1 to 3 stars (`WEIGHTS`): disks, SATA link errors, backups, the watchdog and Docker 3; containers, services, monitors, Tailscale, the radio and heat 2; anything else 1
- a problem left unfixed gains a star per full hour, at most two (`NO_HEAT` lists problems that never do)
- three or more problems at once add one; the level is the worst, capped at 5
- when it drops to zero the stars flash for about two minutes ("evading"); a problem back in that window restores its level quietly, so a flapping check doesn't spam; after that it's "Lost them"

<img src="https://raw.githubusercontent.com/ShaneRunham/ShaneRunham/main/screens/hideout-bot/lost-them.jpg" alt="The Lost them card in #alerts" width="48%">

The level shows in #status's name, the bot's status line ("Wanted ★★☆☆☆ · Container radio is exited"), cards in
#alerts, `/wanted`, Home Assistant (`sensor.wanted_level`), the TV, the dashboards and the phone remote.
Tests: `tests/test_wanted.py`.

## Slash commands

| | |
|---|---|
| `/wanted` | The rap sheet: every current problem, its stars and how long, plus the last 7 days |
| `/radio` | Play, skip or stop Hideout Radio in your voice channel, with a now-playing card |
| `/playtime` | PS5 play time for the last 7 days, per game and per day |
| `/remind` | `30m`, `2h`, `18:00`…: a reminder here and a card on the TV; `/reminders` lists and cancels them |
| `/ask`, `/new` | Ask Claude from any channel; start a fresh conversation |
| `/note` | Save a note |
| `/getfile`, `/clip`, `/type` | Fetch a file from the PC, the PC's clipboard, or type text on the PC |
| `/setup`, `/cleanup` | Rebuild anything missing; clear a channel |

Right-click a message › **Apps › Copy to PC clipboard** sends it to the PC.

## Friends and gaming

- **Joining:** newcomers only see a welcome channel with a "Let me in" button; I approve or deny the request from a card
- **Crew role:** friends get the gaming and lounge channels, nothing else
- **Playing now cards** for me and friends on PlayStation and Switch, with cover art; they say how long you played once you stop
- **Who's online** for PSN and Switch friends
- **Hideout Radio** in voice: friends can listen and skip (not while it's also playing on my TV)

## Claude

In #claude (or `/ask` anywhere) messages go to Claude Code on the PC, with the same safety checks as my own chats. A
conversation carries on until it's been quiet for 30 minutes; images and files attached are passed along.

## Files

`bot.py` starts it · `status.py` the minute loop and #status · `collect.py` the numbers and `problems()` ·
`wanted.py` the Wanted Level · `cards.py` the card helpers · `commands.py` slash commands · `views.py` buttons ·
`server.py` the layout and roles · `gaming.py` / `playtime.py` the consoles · `radio.py` / `radio_voice.py` the radio ·
`claude_chat.py` Claude · `rockstar_news.py` / `gta6.py` GTA VI news · `graphs.py` the 24-hour graphs ·
`make_art.py` the avatar, banner and card headers (the same misty fjord as the TV) ·
`tests/` runs on every push.

> A cleaned copy of my private repo, updated automatically: personal details are swapped for placeholders and
> artwork and fonts are left out.
