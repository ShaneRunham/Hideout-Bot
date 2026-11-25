"""Hideout Radio in Discord voice (/radio): the stream, what's playing, skip, and the album cover.
The station itself is the `radio` container (~/homelab/radio/radio.liq)."""
import hashlib
import json
import os
import urllib.request

STREAM = "http://127.0.0.1:3004/vice-radio"  # the MP3 256 stream the TV plays (the FLAC mount at 256k sounded worse, 2026-11-16)
NOW = "http://127.0.0.1:3005/now"    # JSON: src ("local" or a station), station, artist, title, album, dir
SKIP = "http://127.0.0.1:3005/skip"  # POST: the same skip as the TV and the HA panel
# 600 px album covers, made by vice-tv (~/tv-launcher/service/vice_tv.py radio_covers) for Hideout Home and the HA panel
COVERS = os.path.expanduser("~/homelab/home-assistant/config/www/vice-panel/radio")


def now() -> dict:
    with urllib.request.urlopen(NOW, timeout=5) as r:
        return json.load(r)


def skip():
    urllib.request.urlopen(urllib.request.Request(SKIP, method="POST"), timeout=5).close()


def tv_listening() -> bool:
    """Is the TV playing the radio right now (vice-tv's relay has a listener)? A skip changes the song for everyone."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:5401/api/radio", timeout=3) as r:
            return json.load(r).get("listeners", 0) > 0
    except Exception:  # noqa: BLE001  (vice-tv down: the TV isn't playing it either)
        return False


def may_skip(user_id: int, owner_id: int) -> bool:
    """Shane always; the Crew only while the TV isn't playing the radio (2026-11-16)."""
    return user_id == owner_id or not tv_listening()


SKIP_BLOCKED = "Shane's TV is playing the radio too, so only he can skip right now."


def cover(song: dict) -> str | None:
    """The cover file of one of Shane's own albums (named as vice-tv names it), if it has been made."""
    if not song.get("dir"):
        return None
    path = os.path.join(COVERS, hashlib.sha1(song["dir"].encode()).hexdigest()[:16] + ".jpg")
    return path if os.path.isfile(path) else None


def source(song: dict) -> str:
    if song.get("src") == "local":
        return "Your music" + (f" · {song['album']}" if song.get("album") else "")
    return f"Live from {song['station']}" if song.get("station") else "Live"
