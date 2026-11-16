"""Type text on the PC through a short-lived virtual keyboard on /dev/uinput (blocking; run in a thread).

Shane's user can open /dev/uinput without sudo (KDE Connect's udev rule gives the logged-in user access). Keys are
mapped for the PC's GB layout, so the compositor turns them back into the same characters.
"""
import fcntl
import os
import struct
import time

UI_SET_EVBIT, UI_SET_KEYBIT, UI_DEV_CREATE, UI_DEV_DESTROY = 0x40045564, 0x40045565, 0x5501, 0x5502
EV_SYN, EV_KEY = 0, 1
SHIFT, ENTER = 42, 28

# char: (evdev keycode, shift) for a GB keyboard
KEYS = {" ": (57, False)}
for row, first in (("1234567890", 2), ("qwertyuiop", 16), ("asdfghjkl", 30), ("zxcvbnm", 44)):
    for i, ch in enumerate(row):
        KEYS[ch] = (first + i, False)
        if ch.isalpha():
            KEYS[ch.upper()] = (first + i, True)
for chars, code in (("-_", 12), ("=+", 13), ("[{", 26), ("]}", 27), (";:", 39), ("'@", 40), ("`¬", 41), ("#~", 43),
                    (",<", 51), (".>", 52), ("/?", 53), ("\\|", 86), ("1!", 2), ('2"', 3), ("3£", 4), ("4$", 5),
                    ("5%", 6), ("6^", 7), ("7&", 8), ("8*", 9), ("9(", 10), ("0)", 11)):
    KEYS[chars[0]], KEYS[chars[1]] = (code, False), (code, True)


def unsupported(text: str) -> str:
    """The characters in text that can't be typed (emoji, accents…), deduplicated."""
    return "".join(dict.fromkeys(c for c in text if c not in KEYS))


def type_text(text: str, enter: bool = False):
    fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        for code in {c for c, _ in KEYS.values()} | {SHIFT, ENTER}:
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        # struct uinput_user_dev: name[80], input_id (bustype, vendor, product, version), ff_effects_max, 4 x abs[64]
        os.write(fd, struct.pack("80sHHHHi256i", b"VICE keyboard", 0x06, 0x1, 0x1, 1, 0, *[0] * 256))
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.5)  # give KWin time to pick up the new keyboard

        def key(code, value):
            os.write(fd, struct.pack("llHHi", 0, 0, EV_KEY, code, value))
            os.write(fd, struct.pack("llHHi", 0, 0, EV_SYN, 0, 0))
            time.sleep(0.008)

        for ch in text:
            code, shift = KEYS[ch]
            if shift:
                key(SHIFT, 1)
            key(code, 1)
            key(code, 0)
            if shift:
                key(SHIFT, 0)
        if enter:
            key(ENTER, 1)
            key(ENTER, 0)
        time.sleep(0.1)
        fcntl.ioctl(fd, UI_DEV_DESTROY)
    finally:
        os.close(fd)
