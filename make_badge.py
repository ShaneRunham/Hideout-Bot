"""The server icon (2026-11-16, Shane's pick): the official Beach artwork as a duotone (coral -> gold), "Vice" in the
Yellowtail script (Apache-2.0, assets/fonts) and a "CITY HQ" caption. Writes assets/server-badge.png (1024 px);
make_art.py turns it into server-icon.png. Run: ~/.local/share/homelab-bot-venv/bin/python make_badge.py"""
import os

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(HERE, "assets", "fonts")
ADW = "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf"
ART = os.path.join(HERE, "assets", "scenes")
S = 1024


def font(path, size, weight=None):
    f = ImageFont.truetype(path, size)
    if weight:
        f.set_variation_by_name(weight)
    return f


def text_mask(text, f, cx, cy, stroke=0, track=0.0):
    m = Image.new("L", (S, S), 0)
    d = ImageDraw.Draw(m)
    if not track:
        l, t, r, b = d.textbbox((0, 0), text, font=f, stroke_width=stroke)
        d.text((cx - (l + r) / 2, cy - (t + b) / 2), text, font=f, fill=255, stroke_width=stroke, stroke_fill=255)
        return m
    w = sum(f.getlength(c) for c in text) + track * f.size * (len(text) - 1)
    x = cx - w / 2
    t, b = d.textbbox((0, 0), "H", font=f)[1::2]
    for c in text:
        d.text((x, cy - (t + b) / 2), c, font=f, fill=255)
        x += f.getlength(c) + track * f.size
    return m


def lut_from(stops):
    out = []
    for i in range(256):
        t = i / 255
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0)
                out.append(tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3)))
                break
    return out


def duotone(gray, stops):
    lp = lut_from(stops)
    return Image.merge("RGB", [gray.point([lp[i][ch] for i in range(256)]) for ch in range(3)])


def build(scene, crop, stops, ink, script_fill, accent):
    g = Image.open(f"{ART}/{scene}").convert("L").crop(crop).resize((S, S), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=1)          # full tonal range, so the skyline reads
    img = duotone(g, stops)
    # vignette: darker towards the edges and the bottom, where the caption sits
    v = Image.new("L", (S, S), 0)
    ImageDraw.Draw(v).ellipse((-120, -160, S + 120, S + 60), fill=255)
    v = ImageChops.invert(v.filter(ImageFilter.GaussianBlur(170)))
    img.paste(Image.new("RGB", (S, S), ink), (0, 0), v.point(lambda x: int(x * 0.85)))
    # soft light behind the word
    halo = Image.new("L", (S, S), 0)
    ImageDraw.Draw(halo).ellipse((150, 260, 874, 660), fill=110)
    img = ImageChops.screen(img, Image.composite(Image.new("RGB", (S, S), accent), Image.new("RGB", (S, S)),
                                                 halo.filter(ImageFilter.GaussianBlur(120))))
    # the script: thickened so it survives at chat size, dark lift shadow, then the fill
    f = font(f"{FD}/Yellowtail-Regular.ttf", 400)
    word = text_mask("Vice", f, 512, 455, stroke=7)
    img.paste(Image.new("RGB", (S, S), ink), (10, 16), word.filter(ImageFilter.GaussianBlur(14)))
    img.paste(script_fill, (0, 0), word)
    # caption with thin rules either side
    cap = text_mask("CITY HQ", font(ADW, 58, "Bold"), 512, 712, track=0.34)
    d = ImageDraw.Draw(img)
    l, t, r, b = cap.getbbox()
    for x0, x1 in ((l - 120, l - 34), (r + 34, r + 120)):
        d.rounded_rectangle((x0, 708, x1, 714), 3, fill=accent)
    img.paste(Image.new("RGB", (S, S), (255, 255, 255)), (0, 0), cap)
    return img


if __name__ == "__main__":
    img = build("beach.jpg", (0, 0, 1080, 1080), [(0, (24, 8, 30)), (0.5, (230, 80, 120)), (1, (255, 226, 160))],
                (24, 8, 30), Image.new("RGB", (S, S), (255, 255, 255)), (255, 200, 120))
    img.save(os.path.join(HERE, "assets", "server-badge.png"))
    print("assets/server-badge.png")
