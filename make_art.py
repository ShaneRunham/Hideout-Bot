"""Artwork for the Hideout bot and server (2026-11-25; was the GTA VI "Vice" art): the misty fjord the TV, the phone
and the HA panel show (assets/scenes/fjord-*.jpg, stills of Pexels video 9580491, graded like the TV's loop) for the
profile banner and the card headers (#status, #control, #claude, #commands, #welcome, crew guide); the Hideout
doorway (the same mark as Hideout Phone's icon) for the bot's avatar and the server icon; the flat status-light
emojis. The type is set like the TV home: white, a small tracked caption over a tight title.
Run: ~/.local/share/homelab-bot-venv/bin/python make_art.py   (then restart the bot; it re-applies changed art)"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")
FONT = "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf"  # Adwaita Sans is Inter, the TV home's typeface
INK = (9, 10, 12)  # the TV home's scrim colour (graphite)
LIGHTS = {"v_ok": (126, 226, 168), "v_warn": (255, 197, 107), "v_bad": (255, 138, 122)}  # as on the TV home
OFF, REST = (154, 156, 163), (205, 208, 216)


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
    """A 4:1 band of one of the fjord stills in assets/scenes (2560x1440), starting `top` px down."""
    src = Image.open(os.path.join(OUT, "scenes", name)).convert("RGB")
    return src, (0, top, 2560, top + 640)


def door(size):
    """The Hideout doorway on graphite, full bleed (Discord crops avatars and server icons to a circle)."""
    S = 4 * size
    bg = Image.new("RGB", (S, S))
    g = ImageDraw.Draw(bg)
    for y in range(S):
        t = y / S
        g.line([(0, y), (S, y)], fill=(int(38 - 16 * t), int(40 - 16 * t), int(46 - 17 * t)))
    d = ImageDraw.Draw(bg)
    k = 0.52
    w, h = S * k * 0.62, S * k
    left, top, r = (S - w) / 2, (S - h) / 2, w / 2
    d.pieslice([left, top, left + w, top + w], 180, 360, fill=(242, 242, 242))
    d.rectangle([left, top + r, left + w, top + h], fill=(242, 242, 242))
    d.rectangle([left + w * 0.66, top + r * 0.9, left + w * 0.74, top + h], fill=(24, 25, 29))  # the door ajar
    kr = w * 0.055
    d.ellipse([left + w * 0.46 - kr, top + h * 0.6 - kr, left + w * 0.46 + kr, top + h * 0.6 + kr], fill=(24, 25, 29))
    return bg.resize((size, size), Image.LANCZOS)


def header(src, box, caption, title, name):
    img = cut(src, box, (1200, 300))
    scrim(img, left=0.62, bottom=0.3, overall=0.3)  # the fjord's fog is bright: more shade than the GTA art needed
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
    # the bot's avatar and the server icon: the Hideout doorway
    door(512).save(os.path.join(OUT, "icon.png"))
    door(512).save(os.path.join(OUT, "server-icon.png"))
    # profile banner: the fjord, 5:2, a little shade so the name and status read over it
    ban = cut(Image.open(os.path.join(OUT, "scenes", "fjord-9.jpg")).convert("RGB"), (0, 260, 2560, 1284), (1200, 480))
    scrim(ban, left=0.0, bottom=0.25, overall=0.12)
    ban.convert("RGB").save(os.path.join(OUT, "banner.png"))
    # card headers: one part of the fjord per card, the same scrim and type on each
    header(*scene("fjord-9.jpg", 330), "Hideout · fedora", "Status", "status.jpg")
    header(*scene("fjord-1.jpg", 520), "Hideout · fedora", "Control", "control.png")
    header(*scene("fjord-17.jpg", 250), "Hideout · fedora", "Claude", "claude.png")
    header(*scene("fjord-9.jpg", 240), "Hideout · fedora", "Commands", "commands.png")
    header(*scene("fjord-17.jpg", 560), "The Hideout", "Welcome", "welcome.png")
    header(*scene("fjord-9.jpg", 700), "The Hideout", "Crew guide", "crew-guide.png")
    emojis = {**{k: light(c) for k, c in LIGHTS.items()}, "v_off": light(OFF, ring=True), "v_rest": crescent(REST)}
    for name, im in emojis.items():
        im.save(os.path.join(OUT, "emoji", name + ".png"))
    print("assets: icon.png server-icon.png banner.png status.jpg control.png claude.png commands.png welcome.png crew-guide.png emoji/v_*.png")


if __name__ == "__main__":
    main()
