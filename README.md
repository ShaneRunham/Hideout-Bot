# 🤖 VICE Bot

<img src="https://raw.githubusercontent.com/ShaneRunham/ShaneRunham/main/screens/discord-bot.jpg" alt="VICE's status, control, who's-online and game cards in Discord" width="100%">

A Discord bot for my homelab and my friends, written in Python with [discord.py](https://github.com/Rapptz/discord.py)
and Discord's newer Components v2 cards.

### What it does

- **Live status card** that updates every minute: CPU, memory, temperatures, disks, containers, backups,
  internet speed and what's playing on the TV, plus 24-hour graphs
- **Alerts:** spots problems (hot CPU, a stopped container, a failed backup or CI run) and hands them to Home
  Assistant, which pings my phone and TV
- **Playing now cards** for friends on PlayStation and Nintendo Switch, with cover art and play time
- **Who's online** for PSN and Switch friends
- **GTA VI news** from Rockstar
- **📻 Vice Radio** played into a voice channel ([VICE-Radio](https://github.com/ShaneRunham/VICE-Radio))
- **Control buttons:** screenshot, restart services, TV, PS5, the light, and a channel where Claude answers
- Keeps the server's own layout (categories, channels, roles) in code (`common.py` `LAYOUT`)

### Files

`bot.py` starts it · `status.py` / `cards.py` build the cards · `collect.py` gathers the numbers and problems ·
`gaming.py` / `playtime.py` follow the consoles · `server.py` keeps the layout · `tests/` runs on every push.

> A cleaned copy of my private repo, updated automatically: personal details are swapped for placeholders and
> artwork and fonts are left out.
