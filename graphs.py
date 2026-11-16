"""24-hour history (one reading a minute, kept in history.json) and the graphs image for #status."""
import io
import json
import os
import time
from collections import deque
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import psutil  # noqa: E402
from matplotlib import font_manager  # noqa: E402

KEEP = 24 * 60
NICS = ("enp2s0", "wlp3s0")
# The TV home's look: its typeface, white on dusk, colours sampled from the GTA VI wallpaper
FONT = "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf"
font_manager.fontManager.addfont(FONT)
plt.rcParams["font.family"] = font_manager.FontProperties(fname=FONT).get_name()
BG, GRID, TEXT, DIM = "#15111d", "#2a2435", "#f2eff6", "#a9a2b4"
INDIGO, PINK, PEACH, WHITE, LILAC = "#8f9bf0", "#e07fb6", "#f5b97a", "#f2eff6", "#8d84a6"


class History:
    def __init__(self, path: str):
        self.path = path
        self.rows: deque = deque(maxlen=KEEP)  # (time, cpu, ram, temp, down Mbps, up Mbps, PS3 RSX °C or None)
        self._net = None
        try:
            with open(path) as f:
                self.rows.extend(tuple(r) for r in json.load(f) if r[0] > time.time() - 86400)
        except (OSError, ValueError):
            pass

    def add(self, s: dict):
        now = time.time()
        c = psutil.net_io_counters(pernic=True)
        rx = sum(c[n].bytes_recv for n in NICS if n in c)
        tx = sum(c[n].bytes_sent for n in NICS if n in c)
        down = up = 0.0
        if self._net and now > self._net[0]:
            dt = now - self._net[0]
            down, up = max(0, rx - self._net[1]) * 8 / dt / 1e6, max(0, tx - self._net[2]) * 8 / dt / 1e6
        self._net = (now, rx, tx)
        ps3 = s.get("ps3")
        self.rows.append((now, s["cpu"], s["ram"][0], s["temp"] or 0, round(down, 2), round(up, 2),
                          ps3["rsx"] if ps3 else None))

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(list(self.rows), f)
        os.replace(tmp, self.path)


def _style(ax, title, unit):
    ax.set_facecolor(BG)
    ax.set_title(title, color=TEXT, loc="left", fontsize=13, pad=8)
    ax.text(1.0, 1.02, unit, transform=ax.transAxes, ha="right", va="bottom", color=DIM, fontsize=10)
    ax.grid(True, axis="y", color=GRID, linewidth=0.8)
    for side in ax.spines.values():
        side.set_visible(False)
    ax.tick_params(colors=DIM, labelsize=9, length=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))


def _smooth(y, n=5):
    out, acc = [], 0.0
    for i, v in enumerate(y):
        acc += v - (y[i - n] if i >= n else 0)
        out.append(acc / min(i + 1, n))
    return out


def _line(ax, t, y, colour, label=None):
    y = _smooth(list(y))
    ax.plot(t, y, color=colour, linewidth=1.8, label=label)
    ax.fill_between(t, y, color=colour, alpha=0.10)


def render(history: History, host: str) -> bytes:
    rows = list(history.rows)
    fig, axes = plt.subplots(2, 2, figsize=(12, 6.4), dpi=100, facecolor=BG)
    fig.subplots_adjust(left=0.05, right=0.98, top=0.86, bottom=0.08, hspace=0.45, wspace=0.12)
    fig.text(0.05, 0.94, f"{host} · last 24 hours", color=TEXT, fontsize=17)
    fig.text(0.98, 0.94, datetime.now().strftime("%a %d %b, %H:%M"), color=DIM, fontsize=11, ha="right")
    (cpu_ax, ram_ax), (temp_ax, net_ax) = axes
    if len(rows) < 2:
        for ax in axes.flat:
            ax.axis("off")
        fig.text(0.5, 0.45, "Collecting data… the graphs fill in over the next few minutes",
                 color=DIM, fontsize=14, ha="center")
    else:
        t = [datetime.fromtimestamp(r[0]) for r in rows]
        col = list(zip(*[r[:6] for r in rows]))
        _style(cpu_ax, "CPU", "%")
        _line(cpu_ax, t, col[1], INDIGO)
        cpu_ax.set_ylim(0, 100)
        _style(ram_ax, "Memory", "%")
        _line(ram_ax, t, col[2], PINK)
        ram_ax.set_ylim(0, 100)
        ps3 = [r[6] if len(r) > 6 and r[6] is not None else float("nan") for r in rows]
        has_ps3 = any(v == v for v in ps3)
        _style(temp_ax, "Temperatures" if has_ps3 else "CPU temperature", "°C")
        _line(temp_ax, t, col[3], PEACH, "PC CPU" if has_ps3 else None)
        lo, hi = min(col[3]), max(col[3])
        if has_ps3:  # PS3 RSX, only while it's on: gaps where it was off
            temp_ax.plot(t, ps3, color=LILAC, linewidth=1.8, label="PS3 RSX")
            seen = [v for v in ps3 if v == v]
            lo, hi = min(lo, min(seen)), max(hi, max(seen))
            leg = temp_ax.legend(loc="lower left", ncol=2, frameon=False, fontsize=9)
            for txt in leg.get_texts():
                txt.set_color(DIM)
        temp_ax.set_ylim(max(0, lo - 5), hi + 5)
        _style(net_ax, "Network", "Mbps")
        _line(net_ax, t, col[4], WHITE, "down")
        _line(net_ax, t, col[5], LILAC, "up")
        net_ax.set_ylim(bottom=0)
        leg = net_ax.legend(loc="upper center", ncol=2, frameon=False, fontsize=9)
        for txt in leg.get_texts():
            txt.set_color(DIM)
        for ax, i, fmt in ((cpu_ax, 1, "{:.0f}%"), (ram_ax, 2, "{:.0f}%"), (temp_ax, 3, "{:.0f} °C")):
            ax.text(0.99, 0.92, f"now {fmt.format(col[i][-1])} · peak {fmt.format(max(col[i]))}",
                    transform=ax.transAxes, ha="right", va="top", color=TEXT, fontsize=10)
        net_ax.text(0.99, 0.92, f"now {col[4][-1]:.1f} down · {col[5][-1]:.1f} up", transform=net_ax.transAxes,
                    ha="right", va="top", color=TEXT, fontsize=10)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
