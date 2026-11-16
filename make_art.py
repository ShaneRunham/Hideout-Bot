"""Artwork for the bot and the server, from Rockstar's official GTA VI artwork (assets/scenes, cut from the
rockstargames.com/VI artwork downloads): the bot's avatar (Beach), its profile banner (Rooftop), the card headers
(#status, #control, #claude, #commands, #welcome) and the flat status-light emojis. The server icon is the duotone
badge from make_badge.py. The type is set like the TV home: white, a small tracked caption over a tight title.
Run: ~/.local/share/homelab-bot-venv/bin/python make_art.py   (then restart the bot; it re-applies changed art)"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
FONT = "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf"  # Adwaita Sans is Inter, the TV home's typeface
INK = (10, 6, 20)  # the TV home's scrim colour
LIGHTS = {"v_ok": (126, 226, 168), "v_warn": (255, 197, 107), "v_bad": (255, 138, 122)}  # as on the TV home
OFF, REST = (154, 150, 163), (201, 184, 232)


def font(size, weight):
    f = ImageFont.truetype(FONT, size)
    f.set_variation_by_name(weight)
    return f


def cut(src, box, size):
    return src.crop(box).resize(size, Image.LANCZOS).convert("RGBA")


def scrim(img, left, bottom, overall):
    """Darken like the TV home: a little everywhere, more on the left (behind the words) and along the bottom."""
    w, h = img.size
    across = Image.new("L", (w, 1))
    across.putdata([int(255 * left * max(0.0, 1 - x / (0.7 * w))) for x in range(w)])
    down = Image.new("L", (1, h))
    down.putdata([int(255 * bottom * max(0.0, (y / h - 0.45) / 0.55)) for y in range(h)])
    alpha = ImageChops.add(across.resize((w, h)), down.resize((w, h)))
    alpha = ImageChops.add(alpha, Image.new("L", (w, h), int(255 * overall)))
    img.paste(Image.new("RGBA", (w, h), INK + (255,)), (0, 0), alpha)


def words(img, xy, text, size, weight, tracking, opacity=1.0):
    """Left-aligned white text with letter-spacing in em, as CSS does it."""
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d, f = ImageDraw.Draw(layer), font(size, weight)
    x, y = xy
    for ch in text:
        d.text((x, y), ch, font=f, fill=(255, 255, 255, int(255 * opacity)))
        x += f.getlength(ch) + tracking * size
    img.alpha_composite(layer)


def scene(name, top):
    """A 4:1 band of one of Rockstar's official GTA VI artworks in assets/scenes (the ultrawide versions from
    rockstargames.com/VI/media/artwork-wallpapers, stored at 2560x1080), starting `top` px down."""
    src = Image.open(os.path.join(OUT, "scenes", name)).convert("RGB")
    return src, (0, top, 2560, top + 640)


def header(src, box, caption, title, name):
    img = cut(src, box, (1200, 300))
    scrim(img, left=0.6, bottom=0.3, overall=0.14)
    words(img, (60, 92), caption.upper(), 17, "Medium", 0.18, 0.72)
    words(img, (56, 118), title, 84, "SemiBold", -0.055)
    img.convert("RGB").save(os.path.join(OUT, name), **({"quality": 88} if name.endswith(".jpg") else {}))


def light(colour, ring=False):
    S, r = 512, 120
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    box = (S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r)
    if ring:
        d.ellipse(box, outline=colour + (255,), width=44)
    else:
        d.ellipse(box, fill=colour + (255,))
    return img.resize((128, 128), Image.LANCZOS)


def crescent(colour):
    S, r = 512, 130
    mask = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse((S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r), fill=255)
    d.ellipse((S / 2 - r + 90, S / 2 - r - 50, S / 2 + r + 90, S / 2 + r - 50), fill=0)
    img = Image.new("RGBA", (S, S), colour + (0,))
    img.putalpha(mask)
    return img.resize((128, 128), Image.LANCZOS)


def main():
    os.makedirs(os.path.join(OUT, "emoji"), exist_ok=True)
    # the bot's avatar (2026-11-16, Shane's pick): official Beach artwork, square (Discord shows it as a circle)
    beach = Image.open(os.path.join(OUT, "scenes", "beach-square.jpg")).convert("RGB")
    beach.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon.png"))
    # profile banner (2026-11-16, Shane's pick): official Rooftop artwork, the city at dusk, 5:2
    roof = Image.open(os.path.join(OUT, "scenes", "rooftop.jpg")).convert("RGB")  # 2560x1080
    cut(roof, (0, 20, 2560, 1044), (1200, 480)).convert("RGB").save(os.path.join(OUT, "banner.png"))
    # server icon (2026-11-16, Shane's pick): the duotone "Vice" badge from make_badge.py
    Image.open(os.path.join(OUT, "server-badge.png")).convert("RGB").resize((512, 512), Image.LANCZOS).save(
        os.path.join(OUT, "server-icon.png"))
    # card headers (overhaul 2026-11-16): one Vice City scene per card, the same scrim and type on each
    header(*scene("rooftop.jpg", 30), "Vice · fedora", "Status", "status.jpg")
    header(*scene("robbery.jpg", 160), "Vice · fedora", "Control", "control.png")
    header(*scene("beach.jpg", 150), "Vice · fedora", "Claude", "claude.png")
    header(*scene("car.jpg", 0), "Vice · fedora", "Commands", "commands.png")
    header(*scene("lockandload.jpg", 60), "Vice City HQ", "Welcome", "welcome.png")
    header(*scene("motel.jpg", 40), "Vice City HQ", "Crew guide", "crew-guide.png")
    emojis = {**{k: light(c) for k, c in LIGHTS.items()}, "v_off": light(OFF, ring=True), "v_rest": crescent(REST)}
    for name, im in emojis.items():
        im.save(os.path.join(OUT, "emoji", name + ".png"))
    print("assets: icon.png banner.png status.jpg control.png claude.png commands.png welcome.png emoji/v_*.png")


if __name__ == "__main__":
    main()
