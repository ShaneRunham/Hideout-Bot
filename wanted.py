"""Wanted Level (2026-11-16): the homelab's health as 0-5 stars, worked out every minute from collect.problems().

Each problem is worth 1-3 stars (WEIGHTS); one left unfixed gains a star per full hour (at most +2), and three or more
problems at once add one more. The level is the worst problem's stars, capped at 5. When the level drops to 0 the
displays "evade" for EVADE seconds (the last level flashes); only then is it clear ("Lost them"). A problem back
inside that window restores its level without a new alert. The state lives in wanted.json (not in
git): when each problem started, the clean streak and its record, and the level changes of the last 8 days.

Shown on: #status's name and the bot's presence (status.py), cards in #alerts, /wanted (commands.py), Home Assistant's
sensor.wanted_level (from homelab-state.json) -> phone, TV OSD cards, Hideout panel and Hideout Home (vice-tv /api/status).
"""
from __future__ import annotations

import json
import os
import re

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wanted.json")
EVADE = 110  # s: two minute ticks, so HA (it reads every minute) always sees it
HEAT_EVERY = 3600  # s unfixed per extra star
HEAT_MAX = 2
KEEP = 8 * 86400  # history kept for /wanted's week

# Problems that never gain heat: left on on purpose while working on something (Shane, 2026-11-17)
NO_HEAT = {"tv_ssh"}
# key (or key prefix ending in ":") -> stars. Anything not listed is 1.
WEIGHTS = {
    "disk:": 3, "sata": 3, "docker": 3, "backup": 3, "heartbeat": 3,
    "container:": 2, "user:": 2, "unit:": 2, "kuma": 2, "kuma:": 2, "tailscale": 2, "radio": 2, "temp": 2,
    "update_snapshot": 2,
}


def weight(key: str, msg: str = "") -> int:
    if key.startswith("expiry:"):
        return 3 if " expired on " in msg else 1
    for k, w in WEIGHTS.items():
        if key == k or (k.endswith(":") and key.startswith(k)):
            return w
    return 1


def short(msg: str) -> str:
    """'Container `x` is exited (Exited (1) 2 min ago)' -> 'Container x is exited': the first sentence, no markdown,
    no bracket at its end (the same cut as the TV and the HA panel)."""
    m = re.split(r"\.\s", re.sub(r"[`*]", "", str(msg)))[0]
    return re.sub(r"\s*\((?:[^()]|\([^()]*\))*\)\s*$", "", m)


def load() -> dict:
    try:
        with open(FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(st: dict):
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, FILE)


def update(st: dict, problems: dict[str, str], now: float) -> dict:
    """Work out this minute's level from the problems and the saved state (changed in place, also returned).
    st gains: stars, crimes (worst first), fixed (this minute's problems gone), evading (the level that flashes while evading, else 0), and change against
    the last minute: "up", "down", "evading" (just dropped to 0), "clear" (EVADE later, still 0: lost them) or None.
    A problem back while evading restores its level quietly (a flapping check doesn't spam)."""
    since = {k: st.get("since", {}).get(k, now) for k in problems}
    fixed = [c["what"] for c in st.get("crimes", []) if c["key"] not in problems]
    crimes = []
    for k, msg in problems.items():
        base = weight(k, msg)
        heat = 0 if k in NO_HEAT else min(HEAT_MAX, int((now - since[k]) // HEAT_EVERY))
        crimes.append({"key": k, "what": short(msg), "stars": min(5, base + heat), "base": base, "since": since[k]})
    crimes.sort(key=lambda c: (-c["stars"], c["since"]))
    stars = min(5, (crimes[0]["stars"] if crimes else 0) + (1 if len(crimes) >= 3 else 0))

    before = st.get("stars", 0)
    lost = st.pop("lost", None) if stars else st.get("lost")  # any problem ends the evading
    change = None
    if stars > before:
        # back while evading, no worse than before: straight back to that level without a new alert
        change = None if lost and stars <= lost["stars"] else "up"
        if not before and not lost:  # a fresh start (not a flap): the clean streak ends here
            st["best_clean"] = max(st.get("best_clean", 0), now - st.get("clean_since", now))
    elif stars < before:
        change = "down" if stars else "evading"
        if not stars:
            st["lost"] = {"at": now, "stars": before}
    elif lost and now - lost["at"] >= EVADE:  # evaded the whole window: lost them
        change = "clear"
        st["evaded"] = st.pop("lost")["stars"]
        st["clean_since"] = now
    st.setdefault("clean_since", now)
    lost = st.get("lost")
    if stars != before or change or not st.get("history"):
        st["history"] = [h for h in st.get("history", []) if h[0] > now - KEEP] + [[now, stars]]

    st.update(was=before, since=since, stars=stars, crimes=crimes, evading=lost["stars"] if lost else 0, change=change, fixed=fixed,
              updated=now)
    return st


def for_ha(st: dict) -> dict:
    """What goes into homelab-state.json for HA, the Hideout panel and Hideout Home."""
    return {k: st.get(k) for k in ("stars", "evading", "evaded", "change", "clean_since", "best_clean")} | {
        "crimes": [{"key": c["key"], "what": c["what"], "stars": c["stars"], "since": c["since"]} for c in st.get("crimes", [])]}


def stars_text(n: int, total: int = 5) -> str:
    return "★" * n + "☆" * (total - n)


def day_peaks(history: list, days: list[tuple[float, float]]) -> list[tuple[int, float]]:
    """For each (start, end) day: (peak stars, seconds wanted), from the level changes in history."""
    out = []
    for start, end in days:
        level = 0
        for t, s in history:  # the level in force when the day started
            if t <= start:
                level = s
        peak, wanted, t0 = level, 0.0, start
        for t, s in history:
            if start < t < end:
                if level:
                    wanted += t - t0
                level, t0 = s, t
                peak = max(peak, s)
        if level:
            wanted += end - t0
        out.append((peak, wanted))
    return out
