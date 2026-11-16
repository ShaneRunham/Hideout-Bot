"""PS5 playtime log: the bot's minute tick adds one minute to the game the PS5 shows (PSN status), per day.
playtime.json: {"2026-11-13": {"Call of Duty®": 42}}. Days older than a year are dropped."""
import datetime
import json
import os

FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "playtime.json")


def _load() -> dict:
    try:
        with open(FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def add_minute(game: str, today: datetime.date | None = None):
    today = today or datetime.date.today()
    log = _load()
    day = log.setdefault(today.isoformat(), {})
    day[game] = day.get(game, 0) + 1
    cutoff = (today - datetime.timedelta(days=366)).isoformat()
    log = {d: v for d, v in log.items() if d >= cutoff}
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(log, f, indent=1, ensure_ascii=False)
    os.replace(tmp, FILE)


def week(today: datetime.date | None = None, days: int = 7) -> tuple[dict[str, int], dict[str, int]]:
    """({game: minutes}, {date: minutes}) for the last `days` days including today, games sorted most played first."""
    today = today or datetime.date.today()
    log = _load()
    games, per_day = {}, {}
    for i in range(days):
        d = (today - datetime.timedelta(days=i)).isoformat()
        for g, m in log.get(d, {}).items():
            games[g] = games.get(g, 0) + m
        per_day[d] = sum(log.get(d, {}).values())
    return dict(sorted(games.items(), key=lambda kv: -kv[1])), per_day


def fmt(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"
