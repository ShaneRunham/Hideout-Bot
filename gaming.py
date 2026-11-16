"""PS5 status (PlayStation's local discovery protocol on UDP 9302) and wake-up (through Home Assistant), and whether
someone is streaming from Sunshine right now."""
import re
import socket
import subprocess

PS5_IP = "192.168.0.15"
SUNSHINE_UNIT = "app-dev.lizardbyte.app.Sunshine.service"
PROTO = "device-discovery-protocol-version:00030010\n"


def _ask(message: str, timeout: float = 2.0) -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        s.sendto(message.encode(), (PS5_IP, 9302))
        return s.recvfrom(2048)[0].decode(errors="replace")
    except OSError:
        return None
    finally:
        s.close()


def ps5_state() -> str:
    """'on', 'standby' or 'off' (no answer: switched off at the mains, or off the network)."""
    reply = _ask("SRCH * HTTP/1.1\n" + PROTO)
    if not reply:
        return "off"
    return "on" if reply.startswith("HTTP/1.1 200") else "standby" if " 620 " in reply.split("\n")[0] else "on"


# ---------- Home Assistant: the one route to the PS5's power, the PSN account and the light (2026-11-11) ----------
HA = "http://127.0.0.1:8123"
HA_TOKEN = "~/homelab/home-assistant/token"


def ha(path: str, body: dict | None = None, timeout: float = 30):
    """GET (or POST with a body) to Home Assistant's REST API; returns the parsed JSON."""
    import json
    import os
    import urllib.request
    with open(os.path.expanduser(HA_TOKEN)) as f:
        token = f.read().strip()
    req = urllib.request.Request(HA + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def wake_ps5():
    """Wake the PS5 from rest mode through HA's switch.ps5 (not possible when it's off at the mains)."""
    ha("/api/services/switch/turn_on", {"entity_id": "switch.ps5"})


def psn_playing() -> dict:
    """What the PSN account is playing, from HA's PlayStation Network integration: {"name", "icon", "platform"},
    {} when nothing, {"error": ...} if HA can't be asked. Used by the TV home service (~/tv-launcher/service)."""
    try:
        s = ha("/api/states/media_player.playstation_5", timeout=10)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"[:200]}
    a = s.get("attributes", {})
    if s.get("state") != "playing" or not a.get("media_title"):
        return {}
    pic = a.get("entity_picture")
    return {"name": a["media_title"], "icon": (HA + pic if pic and pic.startswith("/") else pic), "platform": "PS5"}


def psn_friends() -> list[dict]:
    """The PSN friends added to HA's PlayStation Network integration (Settings › Devices › PlayStation Network ›
    Add friend; FriendPSN2 and FriendPSN1 since 2026-11-16), from their sensors:
    [{"name", "status" (offline/availabletoplay/availabletocommunicate/busy), "game" or None, "last" (ISO) or None}]."""
    states = {e["entity_id"]: e["state"] for e in ha("/api/states", None, 15)}
    out = []
    for eid, status in states.items():
        if eid.startswith("sensor.") and eid.endswith("_online_status"):
            base = eid[len("sensor."):-len("_online_status")]
            game = states.get(f"sensor.{base}_now_playing")
            last = states.get(f"sensor.{base}_last_online")
            out.append({"name": states.get(f"sensor.{base}_online_id") or base, "status": status, "base": base,
                        "game": game if game not in (None, "", "unknown", "unavailable") else None,
                        "last": last if last not in (None, "unknown", "unavailable") else None})
    return sorted(out, key=lambda f: f["name"].lower())


def psn_art(base: str) -> bytes | None:
    """The cover of what a PSN friend is playing (HA's image.<base>_now_playing), or None (nothing on, or HA down)."""
    import os
    import urllib.request
    try:
        with open(os.path.expanduser(HA_TOKEN)) as f:
            token = f.read().strip()
        req = urllib.request.Request(f"{HA}/api/image_proxy/image.{base}_now_playing",
                                     headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()
    except Exception:  # noqa: BLE001
        return None


def sunshine_streaming() -> bool:
    """True if Sunshine's log says a client connected and hasn't disconnected since."""
    try:
        started = subprocess.run(["systemctl", "--user", "show", SUNSHINE_UNIT, "-p", "ActiveEnterTimestamp",
                                  "--value"], capture_output=True, text=True, timeout=5).stdout.split()
        if len(started) < 3:  # not running
            return False
        out = subprocess.run(["journalctl", "--user", "-u", SUNSHINE_UNIT, "--since", " ".join(started[1:3]), "-o", "cat",
                              "--no-pager", "-g", "CLIENT (CONNECTED|DISCONNECTED)"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
    except (OSError, subprocess.TimeoutExpired):
        return False
    return bool(out) and out[-1].endswith("CLIENT CONNECTED")


PS3_IP = "192.168.0.163"


def ps3_status() -> dict | None:
    """CPU/RSX temperature and fan speed from webMAN MOD's status page, or None when the PS3 is off or HEN isn't on."""
    import urllib.request
    try:
        html = urllib.request.urlopen(f"http://{PS3_IP}/cpursx.ps3", timeout=3).read().decode("utf-8", "replace")
    except OSError:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    cpu, rsx, fan = (re.search(p, text) for p in (r"CPU:\s*(\d+)\s*°C", r"RSX:\s*(\d+)\s*°C", r"FAN SPEED:\s*(\d+)%"))
    if not (cpu and rsx):
        return None
    return {"cpu": int(cpu.group(1)), "rsx": int(rsx.group(1)), "fan": int(fan.group(1)) if fan else None}


def ps3_cmd(path: str) -> str:
    """Run a webMAN MOD command such as /restart.ps3, /shutdown.ps3, /refresh.ps3 or /mount.ps3/<file>."""
    import urllib.parse
    import urllib.request
    url = f"http://{PS3_IP}" + urllib.parse.quote_plus(path, safe="/[]!;")  # spaces as "+", exactly like webMAN's own links
    return urllib.request.urlopen(url, timeout=15).read().decode("utf-8", "replace")



def ps3_reachable() -> bool:
    """True if the PS3 answers a ping: switched on, even before HEN (and webMAN) is enabled."""
    return subprocess.run(["ping", "-c1", "-W1", PS3_IP], capture_output=True).returncode == 0


SWITCH_IP = "192.168.0.99"  # Nintendo Switch OLED, TV HDMI 2 since 2026-11-16


def switch_awake() -> bool:
    """True if the Switch answers a ping (it has no local API; HA uses the same check)."""
    return subprocess.run(["ping", "-c2", "-W1", SWITCH_IP], capture_output=True).returncode == 0


NXAPI = "http://127.0.0.1:5404"  # the nxapi container (compose.yaml), logged in to the bot's own Nintendo account
NINTENDO_BOT_ID = "5a070a20c2419827"  # that account's Nintendo Account id


def switch_friends() -> list[dict] | None:
    """What the Nintendo Switch Online friends of the bot's Nintendo account are playing (nxapi's API proxy; it gets
    Nintendo's app token through nxapi's f-token service): [{"name", "game", "art", "status", "last"}].
    None when it isn't logged in or Nintendo / the f-token service didn't answer (so sessions aren't ended)."""
    import json
    import urllib.request
    try:
        data = json.load(urllib.request.urlopen(f"{NXAPI}/api/znc/friends?user={NINTENDO_BOT_ID}", timeout=30))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict):
        data = data.get("friends") or []
    out = []
    for f in data:
        p = f.get("presence") or {}
        g = p.get("game") or {}
        state = p.get("state") or "OFFLINE"
        playing = state in ("ONLINE", "PLAYING") and g.get("name")
        out.append({"name": f.get("name"), "game": g["name"] if playing else None,
                    "art": g.get("imageUri") if playing else None,
                    # ONLINE/PLAYING = on; INACTIVE = signed in but the Switch is asleep or idle
                    "status": "online" if state in ("ONLINE", "PLAYING") else "idle" if state == "INACTIVE" else "offline",
                    "last": p.get("logoutAt") or None})  # unix seconds
    return out


def ps3_last_game() -> str | None:
    """The game webMAN last loaded (movies left out), or None."""
    import ftplib
    import io
    buf = io.BytesIO()
    try:
        with ftplib.FTP(PS3_IP, timeout=5) as ftp:
            ftp.login()
            ftp.retrbinary("RETR /dev_hdd0/tmp/wmtmp/last_game.txt", buf.write)
    except (OSError, ftplib.Error):
        return None
    last = buf.getvalue().decode("utf-8", "replace").strip().rsplit("/", 1)[-1]
    if not last or last.startswith("[MOVIES]"):
        return None
    return last.split(".ntfs[")[0].removesuffix(".BIN.ENC").removesuffix(".iso").removesuffix(".ISO") or None


def tv_now() -> dict | None:
    """What the living-room TV is doing, from the couch-tv bridge: {"power", "app", "playing"}, or None."""
    import json
    import os
    import urllib.request
    try:
        with open(os.path.expanduser("~/couch-tv/config.json")) as f:
            key = json.load(f)["bridge"]["pairing_key"]
        req = urllib.request.Request("http://127.0.0.1:5400/api/now?tv=lounge",
                                     headers={"Authorization": f"Bearer {key}"})
        d = json.load(urllib.request.urlopen(req, timeout=8))
    except (OSError, ValueError, KeyError):
        return None
    if not d.get("ok"):
        return None
    app = d.get("app") or {}
    name = app.get("name") or app.get("id") or ""
    m = re.fullmatch(r"com\.webos\.app\.hdmi(\d)", app.get("package") or d.get("screen") or "")
    if m:
        name = {"1": "PS5 (HDMI 1)", "2": "Switch (HDMI 2)", "4": "Sky Box (HDMI 4)"}.get(m.group(1), f"HDMI {m.group(1)}")
    lg = {"com.webos.app.homeconnect": "Home Hub", "com.webos.app.home": "LG home", "com.webos.app.livetv": "Live TV",
          "com.webos.app.inputcommon": "input list", "com.webos.app.launcher": "LG home"}
    if not name and d.get("screen") in lg:
        name = lg[d["screen"]]
    if app.get("package") == "tld.my.customlauncher":
        name = "Hearth"
    if app.get("package", "").startswith("app.couchtv."):
        name = "Vice Home"
    playing = d.get("playing")
    title = (playing.get("title") or playing.get("name")) if isinstance(playing, dict) else None
    return {"power": d.get("power"), "app": name, "playing": title}


def tv_ssh_open() -> bool:
    """True if the LG's SSH server (Homebrew Channel, still on the public default password) is switched on."""
    try:
        with socket.create_connection(("192.168.0.108", 22), timeout=2):
            return True
    except OSError:
        return False


def bridge(path: str, body: dict) -> dict:
    """POST to the couch-tv bridge (the living-room TV)."""
    import json
    import os
    import urllib.request
    with open(os.path.expanduser("~/couch-tv/config.json")) as f:
        key = json.load(f)["bridge"]["pairing_key"]
    req = urllib.request.Request(f"http://127.0.0.1:5400{path}", data=json.dumps({"tv": "lounge", **body}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=30))


def ps5_game() -> str | None:
    """The PS5 game being played, from the TV service (which reads the PSN status), or None."""
    import json
    import os
    import urllib.request
    try:
        with open(os.path.expanduser("~/couch-tv/config.json")) as f:
            key = json.load(f)["bridge"]["pairing_key"]
        req = urllib.request.Request("http://127.0.0.1:5401/api/ps5", headers={"Authorization": f"Bearer {key}"})
        return json.load(urllib.request.urlopen(req, timeout=40)).get("playing")
    except (OSError, ValueError, KeyError):
        return None


def psn_error() -> str | None:
    """None if HA's PlayStation Network login works, else why not (it needs a new NPSSO code)."""
    try:
        entries = ha("/api/config/config_entries/entry?domain=playstation_network", timeout=10)
    except Exception:  # noqa: BLE001 - can't tell: say nothing (HA being down is alerted separately)
        return None
    bad = [e for e in entries if e.get("state") != "loaded"]
    return f"PlayStation Network in Home Assistant: {bad[0].get('state')}" if bad or not entries else None


YT_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|live/)|youtu\.be/)([\w-]{11})")


def youtube_find(query: str) -> tuple[str, str] | None:
    """(video id, title) of the top YouTube result for a search, or None."""
    import json
    import urllib.parse
    import urllib.request
    req = urllib.request.Request("https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
                                 + "&sp=EgIQAQ%253D%253D",
                                 headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "en-GB,en;q=0.9"})
    html = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html)
    if not m:
        return None
    t = re.search(r'"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', html[m.end():m.end() + 4000])
    return m.group(1), (json.loads(f'"{t.group(1)}"') if t else "")


def play_on_tv(text: str) -> str:
    """Play a YouTube link, or the top result for a search, in the TV's YouTube app. Returns what's playing."""
    m = YT_ID.search(text)
    if m:
        vid, title = m.group(1), ""
        try:  # the video's real title, from YouTube's oEmbed
            import json
            import urllib.request
            title = json.load(urllib.request.urlopen(
                f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={vid}&format=json",
                timeout=8)).get("title", "")
        except (OSError, ValueError):
            pass
    else:
        found = youtube_find(text)
        if not found:
            raise RuntimeError("No YouTube video found for that")
        vid, title = found
    import time
    bridge("/api/power", {"state": "on"})
    for attempt in range(6):  # a TV that's just woken refuses apps for a few seconds
        try:
            bridge("/api/launch", {"app": f"https://www.youtube.com/watch?v={vid}"})
            break
        except Exception:  # noqa: BLE001
            if attempt == 5:
                raise
            time.sleep(3)
    return title or f"youtu.be/{vid}"
