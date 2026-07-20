# Hardware abstraction for the M5Stack PaperS3 running UIFlow2 (MicroPython).
#
# This is the ONLY file that talks to M5Unified/UIFlow2 APIs directly. If a method
# name here doesn't match the real firmware, this is the one file to fix - nothing
# else in the app touches M5.* directly. NOT YET VERIFIED ON HARDWARE, see
# m5paper/README.md's build/verification order - method names below are the
# best-known UIFlow2 MicroPython binding names for M5Unified-based devices
# (M5.begin, M5.Display, M5.Touch); the PaperS3's e-paper refresh-mode selection in
# particular is the most likely thing to need adjusting once tested for real.

import M5

WIDTH = 960
HEIGHT = 540

BLACK = 0x000000
WHITE = 0xFFFFFF

_partial_refreshes_since_full = 0


def init():
    """Initialize the display and touch controller. Call once at startup."""
    global WIDTH, HEIGHT
    M5.begin()
    WIDTH = M5.Display.width()
    HEIGHT = M5.Display.height()
    M5.Display.clear(WHITE)


def clear():
    M5.Display.clear(WHITE)


def fill_rect(x, y, w, h, color=WHITE):
    M5.Display.fillRect(x, y, w, h, color)


def rect(x, y, w, h, color=BLACK):
    M5.Display.drawRect(x, y, w, h, color)


def text(s, x, y, color=BLACK, size=1):
    M5.Display.setTextSize(size)
    M5.Display.setTextColor(color, WHITE)
    M5.Display.drawString(s, x, y)


def refresh(full=False):
    """Push the frame buffer to the e-paper panel."""
    global _partial_refreshes_since_full
    M5.Display.display()
    if full:
        _partial_refreshes_since_full = 0
    else:
        _partial_refreshes_since_full += 1


def full_refresh_due(threshold):
    return _partial_refreshes_since_full >= threshold


def poll_touch():
    """Return (x, y) of a current touch press, or None if no touch is active."""
    M5.update()
    if M5.Touch.getCount() > 0:
        detail = M5.Touch.getDetail(0)
        if detail.isPressed() or detail.wasPressed():
            return detail.x, detail.y
    return None
