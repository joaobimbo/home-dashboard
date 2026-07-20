# Hardware abstraction for the M5Stack PaperS3 running UIFlow2 (MicroPython).
#
# This is the ONLY file that talks to M5Unified/UIFlow2 APIs directly. If a method
# name here doesn't match the real firmware, this is the one file to fix - nothing
# else in the app touches M5.* directly.
#
# Verified against the official UIFlow2 MicroPython docs
# (uiflow-micropython.readthedocs.io): the display object is M5.Lcd (class
# M5.Display), drawRect/fillRect/drawString/setTextColor/setTextSize match what's
# used below, and M5.Lcd.setEpdMode() controls e-paper refresh quality/speed - there
# is no separate flush/push call, draws update the panel directly under whichever
# mode is currently set. Touch is M5.Touch.getCount() + M5.Touch.getDetail(0)
# (an 11-element TUPLE, not an object - index 5 is wasPressed) plus separate
# M5.Touch.getX()/getY() calls for coordinates.
#
# Still unverified: whether individual draw calls each visibly flash the panel
# during a redraw, or whether some batching (e.g. startWrite/endWrite) exists to
# make a frame atomic - see m5paper/README.md's verification checklist.

import M5

WIDTH = 960
HEIGHT = 540

BLACK = 0x000000
WHITE = 0xFFFFFF

EPD_QUALITY = 0
EPD_TEXT = 1
EPD_FAST = 2
EPD_FASTEST = 3


def init():
    """Initialize the display and touch controller. Call once at startup."""
    global WIDTH, HEIGHT
    M5.begin()
    WIDTH = M5.Lcd.width()
    HEIGHT = M5.Lcd.height()
    M5.Lcd.setEpdMode(EPD_QUALITY)
    M5.Lcd.clear(WHITE)


def clear():
    M5.Lcd.fillScreen(WHITE)


def fill_rect(x, y, w, h, color=WHITE):
    M5.Lcd.fillRect(x, y, w, h, color)


def rect(x, y, w, h, color=BLACK):
    M5.Lcd.drawRect(x, y, w, h, color)


def text(s, x, y, color=BLACK, size=1):
    M5.Lcd.setTextSize(size)
    M5.Lcd.setTextColor(color, WHITE)
    M5.Lcd.drawString(s, x, y)


def begin_frame(full=False):
    """Call before drawing a frame - sets the e-paper refresh mode for the draw
    calls that follow (there's no separate post-draw flush/push call). Use
    full=True for a clean/ghost-clearing pass (tab switches, periodic
    ghost-clearing), full=False for quick updates (busy-state flips, polls)."""
    M5.Lcd.setEpdMode(EPD_QUALITY if full else EPD_FASTEST)


def poll_touch():
    """Return (x, y) of a new touch press (down-edge only), or None."""
    M5.update()
    if M5.Touch.getCount() > 0:
        detail = M5.Touch.getDetail(0)
        was_pressed = detail[5]  # wasPressed
        if was_pressed:
            return M5.Touch.getX(), M5.Touch.getY()
    return None
