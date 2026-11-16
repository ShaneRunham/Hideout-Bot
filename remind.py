"""/remind: when a reminder is due. Reminders themselves live in the bot's state.json ("reminders"), so they survive
restarts; the bot fires them from a 15-second loop (Discord mention + a Vice OSD card on the TV through HA)."""
import datetime
import re

_DUR = re.compile(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?\s*$", re.I)
_CLOCK = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


def due(when: str, now: datetime.datetime) -> datetime.datetime | None:
    """'30m', '2h', '1h30m' from now, or '18:00' (the next 18:00, today or tomorrow). None if it doesn't parse."""
    m = _CLOCK.match(when)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h > 23 or mi > 59:
            return None
        t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return t if t > now else t + datetime.timedelta(days=1)
    m = _DUR.match(when)
    if m and (m.group(1) or m.group(2)):
        mins = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
        if 0 < mins <= 7 * 24 * 60:
            return now + datetime.timedelta(minutes=mins)
    return None


def say_when(t: datetime.datetime, now: datetime.datetime) -> str:
    """'at 18:00', 'tomorrow at 09:00', 'on Tue at 09:00'."""
    days = (t.date() - now.date()).days
    clock = t.strftime("%H:%M")
    return f"at {clock}" if days == 0 else f"tomorrow at {clock}" if days == 1 else f"on {t.strftime('%a')} at {clock}"
