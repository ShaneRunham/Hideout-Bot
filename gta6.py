"""#gta6: Rockstar Newswire's own GTA VI posts, with the post's picture (Shane's choice, 2026-11-12; it was Google News
until then). The posts come from rockstar_news.py (same feed as Vice Home and the HA panel); this only decides which
ones are new for Discord. State: the post ids already posted, in gta6-state.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "gta6-state.json")


def new_posts(items):
    """Posts from `items` (newest first) not posted before, oldest first. The first run only remembers what's there
    and posts the newest one, so the channel isn't flooded."""
    try:
        with open(STATE_FILE) as f:
            seen = json.load(f).get("rockstar_ids")
    except (OSError, ValueError):
        seen = None
    first = seen is None
    seen = seen or []
    fresh = [x for x in items if x["id"] not in seen]
    out = fresh[:1] if first else list(reversed(fresh))
    seen = [x["id"] for x in items] + [i for i in seen if i not in {x["id"] for x in items}]
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"rockstar_ids": seen[:200]}, f)
    os.replace(tmp, STATE_FILE)
    return out
