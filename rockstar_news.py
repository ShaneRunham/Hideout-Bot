"""Official GTA VI news from Rockstar's Newswire, with each post's photos and videos (Shane's request, 2026-11-12).

Rockstar's site loads the Newswire from its public data service (graph.rockstargames.com, "persisted queries":
fixed query ids taken from the site's own requests). Plain GET requests, nothing pretending to be the site.
If Rockstar changes those ids the fetch fails, the last good file stays, and the bot logs a warning: copy the new
ids from the site's network requests (operationName NewswireList / NewswirePost) into LIST_ID / POST_ID.

bot.py calls update() every 3 hours. It writes FEED, which the HA Hideout panel reads at /local/vice-panel/gta6.json and
vice-tv serves to Hideout Home at /api/gta6. Images and videos stay on Rockstar's and YouTube's servers."""
import datetime
import json
import os
import re
import urllib.parse
import urllib.request

FEED = os.path.expanduser("~/homelab/home-assistant/config/www/vice-panel/gta6.json")
GRAPH = "https://graph.rockstargames.com/"
LIST_ID = "7ec00215aecc70de257b0719a1dfcfa84fe57fdc7bf5c10ec2e8f377defede58"   # NewswireList
POST_ID = "555658813abe5acc8010de1a1feddd6fd8fddffbdc35d3723d4dc0fe4ded6810"   # NewswirePost
GTA6_TAG = 666  # primary tag "Grand Theft Auto VI"
MEDIA = "https://media-rockstargames-com.akamaized.net/"
KEEP = 8


def _graph(op, variables, query_id):
    q = urllib.parse.urlencode({
        "origin": "https://www.rockstargames.com", "operationName": op,
        "variables": json.dumps(variables, separators=(",", ":")),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": query_id}}, separators=(",", ":"))})
    with urllib.request.urlopen(GRAPH + "?" + q, timeout=20) as r:
        data = json.load(r)
    if data.get("errors") or not data.get("data"):  # replies carry "errors": null when all is well
        raise RuntimeError(f"{op}: {data.get('errors') or 'no data'}"[:300])
    return data["data"]


def _when(created):
    """'11/10/26, 3:00 PM' (US style, as the site sends it) -> ISO date."""
    try:
        return datetime.datetime.strptime(created.split(",")[0], "%m/%d/%y").date().isoformat()
    except (ValueError, AttributeError):
        return None


def _media(post):
    """Photos and YouTube video ids attached to a post, in page order.
    Each image in a post's body has "sources": {"en_us": {"desktop": ..., "mobile": ...}} and an "alt" text: take the
    desktop one. (The preview images and the mobile copies would otherwise show every picture two or three times.)"""
    photos = []

    def walk(o):
        if isinstance(o, dict):
            src = ((o.get("sources") or {}).get("en_us") or {}).get("desktop") if isinstance(o.get("sources"), dict) else None
            if isinstance(src, str) and re.search(r"\.(jpe?g|png|webp)$", src):
                # "alt" is a placeholder ("Screenshot/artwork"); the real description is in "_memoq"
                alt = (o.get("_memoq") or {}).get("alt") or o.get("caption") or ""
                alt = "" if not isinstance(alt, str) else alt
                url = MEDIA + src.lstrip("/")
                if url not in [p["url"] for p in photos]:
                    photos.append({"url": url, "alt": alt.strip()})
            for k, v in o.items():
                if k not in ("preview_images", "preview_images_parsed"):
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(post)
    s = json.dumps(post).replace("\\/", "/")
    videos = list(dict.fromkeys(re.findall(r'youtube(?:-nocookie)?\.com/embed/([\w-]{11})', s)))
    return photos, videos


def fetch():
    """The newest GTA VI posts: [{id, title, subtitle, date, url, image, photos: [{url, alt}], videos: [youtube id]}]."""
    posts = _graph("NewswireList", {"tagIdHash": None, "page": 1, "metaUrl": "/newswire", "limit": 20,
                                    "locale": "en_us"}, LIST_ID)["posts"]["results"]
    out = []
    for p in posts:
        if not any(t.get("id") == GTA6_TAG for t in p.get("primary_tags") or []):
            continue
        full = _graph("NewswirePost", {"locale": "en_us", "id_hash": p["id"]}, POST_ID)["post"]
        photos, videos = _media(full)
        preview = (p.get("preview_images_parsed") or {}).get("newswire_block") or {}
        # posts leave "subtitle" empty; the short intro Rockstar shows under the title is the CMS "blurb"
        blurb = (((full.get("tina") or {}).get("payload") or {}).get("meta") or {}).get("blurb") or ""
        out.append({"id": p["id"], "title": p["title"], "subtitle": (full.get("subtitle") or blurb).strip(),
                    "date": _when(p.get("created")), "url": "https://www.rockstargames.com" + p["url"],
                    "image": preview.get("d16x9") or (photos[0]["url"] if photos else None),
                    "photos": photos, "videos": videos})
        if len(out) >= KEEP:
            break
    return out


def update():
    """Fetch and write FEED. Returns the posts; raises on failure (the old file stays)."""
    items = fetch()
    if not items:
        raise RuntimeError("no GTA VI posts found")
    tmp = FEED + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"updated": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                   "items": items}, f)
    os.replace(tmp, FEED)
    return items


if __name__ == "__main__":
    print(len(update()), "posts ->", FEED)
