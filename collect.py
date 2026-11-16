"""Gather the PC/homelab snapshot (blocking; run in a thread) and turn it into alerts and the status embed text."""
import json
import os
import platform
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import psutil

KUMA = "http://127.0.0.1:3001/api/{}/homelab"
SPEEDTEST = "http://127.0.0.1:3002/api/v1/results/latest"  # token: SPEEDTEST_API_TOKEN in .env
FORGEJO = "http://127.0.0.1:3006/api/v1/repos/shane/{}/actions/tasks?limit=20"  # token: FORGEJO_TOKEN in .env
CI_REPOS = ("homelab", "tv-launcher")
BACKUP_LATEST = "/mnt/storage/backups/fedora/latest"
MOUNTS = ("/", "/mnt/storage")
HEARTBEAT_OK = os.path.expanduser("~/.local/state/homelab-heartbeat")
BOOT_GRACE = 5 * 60  # Uptime Kuma takes a minute or two to answer after boot: don't alert on it before this
HEARTBEAT_LATE = 15 * 60  # pings go every 5 min; healthchecks.io itself alerts after 5 + 15 min
UNITS = ("homelab-backup.service", "homelab-update.service", "homelab-smart-check.service", "homelab-scrub.service")

# alert thresholds
TEMP_C, RAM_PCT, DISK_PCT, BACKUP_MAX_AGE = 85, 92, 90, 26 * 3600
PS3_HOT_C = 80  # CPU or RSX; webMAN holds 73 °C, so this means the fan is losing


def _cmd(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)


def _json(url, headers=None):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=8) as r:
        return json.load(r)


def cpu_temp():
    temps = psutil.sensors_temperatures()
    for name in ("coretemp", "k10temp", "cpu_thermal"):
        if temps.get(name):
            return temps[name][0].current
    return None


def parallel(jobs: dict) -> dict:
    """Run blocking checks at the same time: {key: fn} -> {key: result}. A check that raises gives None (each one
    already handles its own expected failures; this only keeps one surprise from losing the whole snapshot)."""
    def safe(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return None
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(safe, fn) for k, fn in jobs.items()}
        return {k: f.result() for k, f in futures.items()}


def _containers():
    code, out = _cmd(["docker", "ps", "-a", "--format", "{{json .}}"])
    return ({c["Names"]: (c["State"], c["Status"]) for c in map(json.loads, filter(None, out.splitlines()))}
            if code == 0 else None)


def _kuma():
    page, beats = _json(KUMA.format("status-page")), _json(KUMA.format("status-page/heartbeat"))
    out = {}
    for g in page["publicGroupList"]:
        for m in g["monitorList"]:
            hb = (beats["heartbeatList"].get(str(m["id"])) or [{}])[-1]
            out[m["name"]] = hb.get("status")
    return out


def _tailscale():
    code, out = _cmd(["tailscale", "status", "--json"])
    if code != 0:
        return None
    d = json.loads(out)
    return {"state": d.get("BackendState"),
            "peers": {p.get("HostName", "?"): bool(p.get("Online")) for p in (d.get("Peer") or {}).values()}}


def _units():
    # one systemctl call for all of them: a block of "ActiveState\nResult" per unit, blank line between
    code, out = _cmd(["systemctl", "show", *UNITS, "-p", "ActiveState", "-p", "Result", "--value"])
    blocks = out.strip("\n").split("\n\n") if code == 0 else []
    res = {}
    for u, block in zip(UNITS, blocks + [""] * len(UNITS)):
        state, result = (block.split() + ["?", "?"])[:2]
        res[u] = "failed" if state == "failed" or result not in ("success", "?") else "ok"
    return res


RADIO_STREAM = "http://127.0.0.1:3004/vice-radio"


def radio_stream() -> bool:
    """Is Vice Radio serving its stream? Liquidsoap sometimes comes up playing but without the stream's web handler
    (a 404 or a dropped connection on /vice-radio), and Uptime Kuma only watches /now, which stays up (2026-11-16)."""
    try:
        with urllib.request.urlopen(RADIO_STREAM, timeout=4) as r:
            return r.status == 200 and bool(r.read(1))
    except Exception:  # noqa: BLE001
        return False


def _speed():
    d = _json(SPEEDTEST, {"Accept": "application/json",
                          "Authorization": "Bearer " + os.environ.get("SPEEDTEST_API_TOKEN", "")})["data"]
    # Speedtest Tracker marks a result unhealthy when it misses its thresholds (download 500, upload 50 Mbps)
    return ((d["download_bits_human"], d["upload_bits_human"], d["ping"]),
            (d["download_bits_human"], d["upload_bits_human"]) if d.get("healthy") is False else None)


def snapshot(extra: dict | None = None) -> dict:
    """The PC/homelab snapshot. The slow parts (commands, local web APIs) run at the same time, together with any
    `extra` checks ({key: fn}, e.g. the consoles and the TV from gaming.py), whose results land in s[key]."""
    s = {"time": time.time(), "host": platform.node()}
    r = parallel({"cpu": lambda: psutil.cpu_percent(interval=0.5), "containers": _containers, "kuma": _kuma,
                  "tailscale": _tailscale, "units": _units, "speed": _speed, "sata_errors": sata_errors,
                  "ci_failed": ci_failed, "expiries": expiries, "radio_stream": radio_stream, **(extra or {})})
    s["cpu"] = r.pop("cpu") or 0.0
    s["speed"], s["speed_slow"] = r.pop("speed") or (None, None)
    s["units"] = r.pop("units") or {}
    s.update(r)
    s["temp"] = cpu_temp()
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    s["ram"] = (vm.percent, vm.used, vm.total)
    s["swap"] = (sw.percent, sw.used, sw.total)
    s["load"] = os.getloadavg()
    s["uptime"] = time.time() - psutil.boot_time()
    s["disks"] = {}
    for m in MOUNTS:
        try:
            u = psutil.disk_usage(m)
            s["disks"][m] = (u.percent, u.used, u.total)
        except OSError:
            s["disks"][m] = None

    try:
        s["backup"] = (os.path.basename(os.readlink(BACKUP_LATEST)), time.time() - os.lstat(BACKUP_LATEST).st_mtime)
    except OSError:
        s["backup"] = None

    try:  # written by the root homelab-kernel-default.timer (~/homelab/kernel), e.g. /boot/vmlinuz-7.2.15-200.fc44.x86_64
        with open("/run/kernel-default") as f:
            s["kernel_default"] = f.read().strip().removeprefix("/boot/vmlinuz-")
    except OSError:
        s["kernel_default"] = None
    s["kernel"] = platform.release()
    s["ci_failed"] = s["ci_failed"] or {}
    s["expiries"] = s["expiries"] or {}
    try:  # written by the root homelab-update-snapshot (~/homelab/update-snapshot) in each offline-update boot
        with open("/var/lib/homelab/update-snapshot.status") as f:
            s["update_snapshot"] = f.read().strip()
    except OSError:
        s["update_snapshot"] = None
    try:  # last ping that reached healthchecks.io, written by ~/homelab/heartbeat/heartbeat.sh
        s["heartbeat_age"] = time.time() - os.path.getmtime(HEARTBEAT_OK)
    except OSError:
        s["heartbeat_age"] = None
    s["uptime"] = time.time() - psutil.boot_time()
    return s


_restart_cache = [0.0, None]


USER_UNITS = {"vice-tv.service": "TV home service (vice-tv)", "couch-tv-bridge.service": "TV bridge (couch-tv)",
              "ps3-backup.timer": "PS3 save backup timer", "app-dev.lizardbyte.app.Sunshine.service": "Sunshine",
              "govee-bridge.service": "Light bridge for Home Assistant (govee-bridge)",
              "pc-actions.service": "PC buttons for Home Assistant (pc-actions)",
              "jarvis-assist-tts.service": "JARVIS voice for Assist (jarvis-assist-tts)",
              "jarvis-assist-claude.service": "JARVIS Claude agent for Assist (jarvis-assist-claude)",
              "syncthing.service": "PSP save sync with the tablet (Syncthing)"}


def user_units() -> dict[str, bool]:
    """{unit: running} for the user services the TV, phone remote and PS3 backup depend on."""
    # one call for all: is-active prints one state per unit, in order
    r = subprocess.run(["systemctl", "--user", "is-active", *USER_UNITS], capture_output=True, text=True)
    states = r.stdout.split()
    return {u: i < len(states) and states[i] == "active" for i, u in enumerate(USER_UNITS)}


def restart_needed() -> str | None:
    """Why a restart is needed (updates staged, or core packages updated since boot), else None. Checked every 10 min."""
    if time.time() - _restart_cache[0] < 600:
        return _restart_cache[1]
    reason = None
    if os.path.lexists("/system-update") or os.path.exists("/var/lib/PackageKit/prepared-update"):
        reason = "updates are downloaded and install when you restart"
    else:
        try:  # -C: cached metadata only (no downloads). Exit 1 also means a dnf error (e.g. no cache), so read the text
            out = subprocess.run(["dnf5", "-C", "needs-restarting", "-r"], capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        if "Reboot is required" in out:
            reason = "core updates (kernel or system libraries) were installed since the last restart"
    _restart_cache[:] = [time.time(), reason]
    return reason


def ci_failed() -> dict[str, list[str]]:
    """Forgejo checks (.forgejo/workflows) that failed on each repo's latest checked commit: {repo: [job names]}.
    Forgejo down means no answer here; the container check reports that instead."""
    out = {}
    for repo in CI_REPOS:
        try:
            tasks = _json(FORGEJO.format(repo), {"Authorization": "token " + os.environ.get("FORGEJO_TOKEN", "")})
            tasks = tasks["workflow_runs"]
        except Exception:
            continue
        if tasks:  # newest first
            failed = [t["name"] for t in tasks if t["head_sha"] == tasks[0]["head_sha"] and t["status"] == "failure"]
            if failed:
                out[repo] = failed
    return out


def sata_errors(since: str = "-24h") -> tuple[int, str, str] | None:
    """(count, latest 'HH:MM', ports) for kernel 'ataN: SError' lines (SATA link errors) in the last 24 h, else None.
    _TRANSPORT=kernel, not -k: -k only reads the current boot."""
    rc, out = _cmd(["journalctl", "_TRANSPORT=kernel", "--since", since, "-g", r"ata[0-9]+: SError",
                    "-o", "short-iso", "-q", "--no-pager"])
    lines = [ln for ln in out.splitlines() if " kernel: ata" in ln] if rc == 0 else []
    if not lines:
        return None
    ports = sorted({ln.split(" kernel: ")[1].split(":")[0] for ln in lines})
    return len(lines), lines[-1][11:16], ", ".join(ports)


EXPIRIES = os.path.expanduser("~/homelab/expiries.json")
HA_TOKEN = os.path.expanduser("~/homelab/home-assistant/token")
TAILNET_HOST = "fedora.tailnet.ts.net"
EXPIRY_WARN = 14 * 86400
_expiry_cache = [0.0, {}]


def expiries() -> dict[str, tuple[float, str]]:
    """{name: (expires at, how to renew)} for logins and certificates. Checked once an hour."""
    if time.time() - _expiry_cache[0] < 3600:
        return _expiry_cache[1]
    import base64
    import datetime
    import socket
    import ssl
    out = {}
    try:  # Tailscale node key (KeyExpiry is absent while key expiry is disabled for this machine)
        rc, txt = _cmd(["tailscale", "status", "--json"])
        exp = json.loads(txt)["Self"].get("KeyExpiry") if rc == 0 else None
        if exp:
            out["Tailscale login"] = (datetime.datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp(),
                                      "Run `tailscale up --force-reauth`, or turn off key expiry in the admin console")
    except (ValueError, KeyError):
        pass
    try:  # the tailnet HTTPS certificate (tailscale serve renews it itself; this catches a renewal that fails)
        ctx = ssl.create_default_context()
        with socket.create_connection((TAILNET_HOST, 443), timeout=8) as sock, \
                ctx.wrap_socket(sock, server_hostname=TAILNET_HOST) as tls:
            out["Tailnet HTTPS certificate"] = (ssl.cert_time_to_seconds(tls.getpeercert()["notAfter"]),
                                                "Tailscale renews it: check `tailscale serve status` and the journal")
    except (OSError, ssl.SSLError, KeyError, ValueError):
        pass
    try:  # Home Assistant long-lived token (bot, Vice TV, scripts): a JWT with an exp claim
        with open(HA_TOKEN) as f:
            part = f.read().strip().split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))).get("exp")
        if exp:
            out["Home Assistant token"] = (float(exp), "Make a new long-lived token in HA (profile > Security) "
                                                       "and put it in ~/homelab/home-assistant/token")
    except (OSError, IndexError, ValueError):
        pass
    try:  # dates nothing can read, e.g. the PSN npsso
        with open(EXPIRIES) as f:
            for name, v in json.load(f).items():
                if not name.startswith("_"):
                    out[name] = (datetime.datetime.fromisoformat(v["date"]).timestamp(), v.get("how", ""))
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    _expiry_cache[:] = [time.time(), out]
    return out


def gta6_feed_stale(max_age: float = 2 * 86400) -> str | None:
    """'12 Nov 21:04' if the Rockstar GTA VI feed (rockstar_news.py, every 3 hours) hasn't been written for 2 days."""
    f = os.path.expanduser("~/homelab/home-assistant/config/www/vice-panel/gta6.json")
    try:
        at = os.path.getmtime(f)
    except OSError:
        return None  # never written yet: nothing to compare
    return time.strftime("%d %b %H:%M", time.localtime(at)) if time.time() - at > max_age else None


def problems(s: dict, hot_count: int = 0) -> dict[str, str]:
    """Current problems as {stable key: message}. hot_count = consecutive hot readings before this one."""
    p = {}
    if s["temp"] is not None and s["temp"] >= TEMP_C and hot_count >= 2:
        p["temp"] = f"CPU at {s['temp']:.0f} °C for 3+ minutes"
    if s["ram"][0] >= RAM_PCT:
        p["ram"] = f"Memory {s['ram'][0]:.0f}% used"
    for m, d in s["disks"].items():
        if d is None:
            p[f"disk:{m}"] = f"`{m}` isn't mounted"
        elif d[0] >= DISK_PCT:
            p[f"disk:{m}"] = f"`{m}` is {d[0]:.0f}% full"
    if s["containers"] is None:
        p["docker"] = "Can't reach Docker"
    else:
        for name, (state, status) in s["containers"].items():
            if state != "running":
                p[f"container:{name}"] = f"Container `{name}` is {state} ({status})"
            elif "(unhealthy)" in status:  # running but failing its own health check, e.g. hung
                p[f"container:{name}"] = f"Container `{name}` is unhealthy ({status})"
    if s.get("uptime", BOOT_GRACE) < BOOT_GRACE:
        pass
    elif s["kuma"] is None:
        p["kuma"] = "Uptime Kuma isn't answering"
    else:
        for name, st in s["kuma"].items():
            if st == 0:
                p[f"kuma:{name}"] = f"Uptime Kuma: **{name}** is down"
    if s["tailscale"] is None or s["tailscale"]["state"] != "Running":
        p["tailscale"] = "Tailscale isn't running"
    if s["backup"] is None:
        p["backup"] = "Can't find the latest backup"
    elif s["backup"][1] > BACKUP_MAX_AGE:
        p["backup"] = f"Last backup is {s['backup'][1] / 3600:.0f} h old"
    if s.get("speed_slow"):
        p["speed"] = "Internet is slow. The last speed test got {} down, {} up (Speedtest Tracker)".format(*s["speed_slow"])
    ps3 = s.get("ps3")
    if ps3 and max(ps3["cpu"], ps3["rsx"]) >= PS3_HOT_C:
        p["ps3"] = f"PS3 running hot: CPU {ps3['cpu']} °C, RSX {ps3['rsx']} °C, fan {ps3['fan']}%"
    for u, running in (s.get("user_units") or {}).items():
        if not running:
            p[f"user:{u}"] = f"{USER_UNITS.get(u, u)} has stopped (`systemctl --user restart {u}`)"
    if s.get("psn_error"):
        p["psn"] = ("The PSN login in Home Assistant has stopped working. Renew it: sign in at playstation.com, open "
                    "ca.account.sony.com/api/v1/ssocookie and give Claude the npsso code (HA and ps5-mqtt use it)")
    if s.get("radio_down", 0) >= 5:
        p["radio"] = ("Vice Radio isn't serving its stream (TV and Discord radio are silent), and restarting it didn't "
                      "help. Try #control › Restart a service › radio, or check `docker logs radio`")
    if s.get("ps3_nohen", 0) >= 3:
        p["ps3_hen"] = "The PS3 is on without HEN. Select Enable HEN on the XMB"
    stale = gta6_feed_stale()
    if stale:
        p["gta6_feed"] = (f"The GTA VI news hasn't updated since {stale}. Rockstar may have changed its site: see "
                          "~/homelab/discord-bot/rockstar_news.py (LIST_ID / POST_ID)")
    if s.get("tv_ssh"):
        # the first sentence is what the TV and the HA panel show in their status line: keep it short
        p["tv_ssh"] = ("The TV's SSH server is on. It still takes the public default password: "
                       "turn it off in Homebrew Channel > Settings > SSH Server")
    if s.get("kernel_default") and s["kernel_default"] != s["kernel"]:
        p["kernel"] = (f"A different kernel boots next. The next restart boots kernel {s['kernel_default']}, "
                       f"not {s['kernel']}. If it's untested, keep "
                       f"the current one: `sudo grubby --set-default /boot/vmlinuz-{s['kernel']}`")
    for repo, jobs in (s.get("ci_failed") or {}).items():
        p[f"ci:{repo}"] = (f"Checks failed on the latest {repo} commit: {', '.join(jobs)}. "
                           f"See https://fedora.tailnet.ts.net:8448/shane/{repo}/actions")
    if s.get("sata_errors"):
        n, at, ports = s["sata_errors"]
        p["sata"] = (f"SATA link errors on {ports}: {n} in the last 24 h, latest {at}. ata5 is the boot SSD: "
                     "see ~/CLAUDE.md › Open items (link power saving, then the cable)")
    if (s.get("update_snapshot") or "").startswith("failed"):
        p["update_snapshot"] = (f"No snapshot was taken before the last Fedora update, so it can't be undone from the "
                                f"boot menu. {s['update_snapshot']} (~/homelab/update-snapshot)")
    for name, (at, how) in (s.get("expiries") or {}).items():
        left = at - (s.get("time") or time.time())
        if left < EXPIRY_WARN:
            when = time.strftime("%d %b", time.localtime(at))
            state = f"expired on {when}" if left < 0 else f"expires in {max(1, round(left / 86400))} days ({when})"
            p[f"expiry:{name}"] = f"{name} {state}. {how}"
    hb = s.get("heartbeat_age")
    if s.get("uptime", 0) > HEARTBEAT_LATE and (hb is None or hb > HEARTBEAT_LATE):
        ago = "since boot" if hb is None or hb > s["uptime"] else f"for {hb / 60:.0f} min"
        p["heartbeat"] = (f"The outside watchdog isn't getting pings. None has reached healthchecks.io {ago}, so it "
                          "would alert as if the PC were down. Internet down, or see `journalctl --user -u heartbeat`")
    for u, st in s["units"].items():
        if st == "failed":
            p[f"unit:{u}"] = f"`{u.removesuffix('.service')}` failed its last run (`journalctl -u {u}`)"
    return p






# status lights; the bot swaps in the server's own flat dots (assets/emoji) when they exist
EMOJI = {"ok": "🟢", "warn": "🟡", "bad": "🔴", "off": "⚫", "rest": "🌙"}






def dur(sec):
    sec = int(sec)
    d, h, m = sec // 86400, sec % 86400 // 3600, sec % 3600 // 60
    return f"{d}d {h}h" if d else f"{h}h {m}m" if h else f"{m}m"


def gb(n):
    return f"{n / 1e9:.0f}" if n >= 100e9 else f"{n / 1e9:.1f}"


def status_parts(s: dict, probs: dict, emoji: dict | None = None) -> dict:
    """What the #status card shows: colour ('green'/'gold'/'red'), summary (for the channel name and the bot's
    presence), title, sub (the small line under it), alert (problems and a pending restart, or "") and sections
    [(heading, text)]. Written like the TV home: a short personal headline, plain labels, a light only where it says
    something, and lists only of what isn't fine (12 green container names said nothing)."""
    e = {**EMOJI, **(emoji or {})}
    ok, warn, bad_, off = e["ok"], e["warn"], e["bad"], e["off"]
    n = len(probs)
    if n:
        summary, colour = f"{n} problem{'s' if n > 1 else ''}", "red"
        title = f"{summary.capitalize()}, Shane."
    elif s["cpu"] > 85 or s["ram"][0] > 85:
        summary, colour, title = "working hard", "gold", "Working hard, Shane."
    else:
        summary, colour, title = "all quiet", "green", "All quiet, Shane."
    alert = [f"{bad_} {t}" for t in list(probs.values())[:6]]
    if n > 6:
        alert.append(f"-# and {n - 6} more")
    if s.get("restart"):
        alert.append(f"**Restart needed:** {s['restart']}. Use **Restart** in #control.")
    sub = f"{s['host']} · up {dur(s['uptime'])} · <t:{int(s['time'])}:R>"

    def mark(pct, warn_at, bad_at):  # nothing while it's fine
        return "" if pct < warn_at else (warn if pct < bad_at else bad_) + " "

    temp = f" · {s['temp']:.0f} °C" if s["temp"] is not None else ""
    r, w = s["ram"], s["swap"]
    pc = [f"**CPU** {mark(s['cpu'], 70, 90)}{s['cpu']:.0f}%{temp}",
          f"**Memory** {mark(r[0], 80, 92)}{r[0]:.0f}% · {gb(r[1])} / {gb(r[2])} GB",
          f"**Swap** {mark(w[0], 60, 85)}{w[0]:.0f}% · {gb(w[1])} / {gb(w[2])} GB"]
    labels = {"/": "System disk", "/mnt/storage": "Storage"}
    for m, d in s["disks"].items():
        pc.append(f"**{labels.get(m, m)}** " + (f"{mark(d[0], 75, 90)}{d[0]:.0f}% · {gb(d[2] - d[1])} GB free"
                                                if d else f"{bad_} not mounted"))
    pc.append(f"**Internet** {s['speed'][0]} down · {s['speed'][1]} up · {s['speed'][2]:.0f} ms"
              if s.get("speed") else "**Internet** no speed test yet")
    sections = [("PC", "\n".join(pc))]

    if "ps5" in s:
        on, idle = [], []
        tv = s.get("tv")
        if not tv or tv["power"] not in ("on", None):
            idle.append("TV")
        else:
            on.append(f"📺 **TV** · {tv['app'] or 'on'}" + (f" · {tv['playing'][:40]}" if tv.get("playing") else ""))
        if s["ps5"] == "on":
            on.append("🎮 **PS5**" + (f" · {s['ps5_game'][:40]}" if s.get("ps5_game") else " · on"))
        else:
            idle.append("PS5 resting" if s["ps5"] == "standby" else "PS5")
        if s.get("nsw"):
            on.append("🎮 **Switch** · on" + (" · on the TV" if tv and "Switch" in (tv.get("app") or "") else ""))
        else:
            idle.append("Switch")
        p3 = s.get("ps3")
        if p3:
            hot = max(p3["cpu"], p3["rsx"]) >= PS3_HOT_C
            on.append(f"🕹️ **PS3**{' ' + bad_ if hot else ''}" + (f" · {s['ps3_game'][:40]}" if s.get("ps3_game") else " · on")
                      + f" · {max(p3['cpu'], p3['rsx']):.0f} °C")
        elif s.get("ps3_up"):
            on.append(f"🕹️ **PS3** · {warn} on, enable HEN")
        # an off PS3 isn't listed: it's unplugged since 2026-11-16 (the Switch has HDMI 2)
        if s.get("streaming"):
            on.append("🖥️ **Moonlight** · streaming the PC")
        else:
            idle.append("Moonlight")
        sections.append(("Now playing", "\n".join((on or ["Nothing on right now"])
                                                   + ([f"-# Off: {' · '.join(idle)}"] if idle else []))))

    lab = []
    if s["containers"] is None:
        lab.append(f"{bad_} **Docker** unreachable")
    else:
        down = sorted((name, st) for name, (st, _) in s["containers"].items() if st != "running")
        lab.append(f"{bad_ if down else ok} **Containers** {len(s['containers']) - len(down)}/{len(s['containers'])} running")
        lab += [f"-# {bad_} {name} · {st}" for name, st in down]
    if s["kuma"] is None:
        lab.append(f"{bad_} **Uptime Kuma** not answering")
    else:
        down = [k for k, v in s["kuma"].items() if v != 1]
        lab.append(f"{bad_ if down else ok} **Services** {len(s['kuma']) - len(down)}/{len(s['kuma'])} up")
        lab += [f"-# {bad_ if s['kuma'][k] == 0 else warn if s['kuma'][k] == 2 else off} {k}" for k in down]
    if s["tailscale"]:
        peers = s["tailscale"]["peers"]
        away = sorted(h[:22] for h, online in peers.items() if not online)
        lab.append(f"{ok} **Tailscale** {len(peers) - len(away)}/{len(peers)} devices online")
        if away:
            lab.append(f"-# Offline: {' · '.join(away)}")
    else:
        lab.append(f"{bad_} **Tailscale** not running")
    b = s["backup"]
    failed = [u.removeprefix("homelab-").removesuffix(".service") for u, st in s["units"].items() if st != "ok"]
    lab.append((f"{ok} **Backup** {dur(b[1])} ago" if b else f"{bad_} **Backup** none found")
               + (f" · {bad_} failed: {', '.join(failed)}" if failed else " · nightly jobs fine"))
    sections.append(("Homelab", "\n".join(lab)))
    return {"title": title, "sub": sub, "alert": "\n".join(alert), "summary": summary, "colour": colour,
            "sections": sections}


WMO = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "cloudy", 45: "fog", 48: "fog", 51: "light drizzle",
       53: "drizzle", 55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow",
       73: "snow", 75: "heavy snow", 80: "showers", 81: "showers", 82: "heavy showers", 95: "thunderstorms"}


def weather_today() -> str | None:
    """Today's forecast for the TV home's place (couch-tv config), from Open-Meteo."""
    try:
        with open(os.path.expanduser("~/couch-tv/config.json")) as f:
            w = json.load(f)["weather"]
        d = _json(f"https://api.open-meteo.com/v1/forecast?latitude={w['lat']}&longitude={w['lon']}"
                  "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                  f"&timezone={w.get('timezone', 'auto')}&forecast_days=1")["daily"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    code = d["weather_code"][0]
    sky = WMO.get(code, WMO.get(code - code % 10, "mixed"))
    rain = d["precipitation_probability_max"][0] or 0
    return (f"{w.get('place', 'Today')}: {sky}, {d['temperature_2m_min'][0]:.0f}–{d['temperature_2m_max'][0]:.0f} °C"
            + (f", {rain:.0f}% chance of rain" if rain >= 30 else ""))


def morning_text(s: dict, probs: dict) -> str:
    """The 8 am summary: overnight jobs, speed, problems, PS3 save backup, weather."""
    lines = []
    b = s["backup"]
    lines.append(f"**Backup** {'ran ' + dur(b[1]) + ' ago' if b else 'not found'}"
                 + ("" if not s["units"] else " · " + ", ".join(
                     f"{u.removeprefix('homelab-').removesuffix('.service')} {'ok' if st == 'ok' else '**failed**'}"
                     for u, st in s["units"].items())))
    if s.get("speed"):
        lines.append(f"**Internet** {s['speed'][0]} down, {s['speed'][1]} up, {s['speed'][2]:.0f} ms")
    try:
        ps3 = json.load(open(os.path.expanduser("~/homelab/ps3-backup/last-run.json")))
        lines.append(f"**PS3 saves** last copied {dur(time.time() - ps3['ok_at'])} ago ({ps3['files']} files)")
    except (OSError, ValueError, KeyError):
        pass
    lines.append("**Problems** none" if not probs else "**Problems**\n" + "\n".join(f"• {p}" for p in probs.values()))
    w = weather_today()
    if w:
        lines.append(f"**Weather** {w}")
    return "\n".join(lines)
