# Screen geometry and touch hit-testing. No hardware calls here - pure math, so it
# stays testable/adjustable independent of hw.py's on-device verification.

import hw

TAB_AC = "ac"
TAB_LIGHTS = "lights"
TAB_COVERS = "covers"
TAB_LABELS = {TAB_AC: "AC", TAB_LIGHTS: "Luzes", TAB_COVERS: "Estores"}

HEADER_H = 70
TABS_H = 60
FOOTER_H = 30

GRID_COLS = 2
GRID_ROWS = 3
TILE_PAD = 8


def header_rect():
    return (0, 0, hw.WIDTH, HEADER_H)


def tabs_rect():
    return (0, HEADER_H, hw.WIDTH, TABS_H)


def tab_button_rect(index, count):
    w = hw.WIDTH // max(count, 1)
    x0, y0, _, h = tabs_rect()
    return (x0 + index * w, y0, w, h)


def body_rect():
    top = HEADER_H + TABS_H
    bottom = hw.HEIGHT - FOOTER_H
    return (0, top, hw.WIDTH, bottom - top)


def footer_rect():
    return (0, hw.HEIGHT - FOOTER_H, hw.WIDTH, FOOTER_H)


def page_size():
    return GRID_COLS * GRID_ROWS


def tile_rect(slot):
    """slot is 0-indexed position within the current grid page."""
    bx, by, bw, bh = body_rect()
    col = slot % GRID_COLS
    row = slot // GRID_COLS
    tw = bw // GRID_COLS
    th = bh // GRID_ROWS
    return (bx + col * tw + TILE_PAD, by + row * th + TILE_PAD, tw - 2 * TILE_PAD, th - 2 * TILE_PAD)


def ac_row_rect(slot, total_rows):
    bx, by, bw, bh = body_rect()
    rh = bh // max(total_rows, 1)
    return (bx + TILE_PAD, by + slot * rh + TILE_PAD, bw - 2 * TILE_PAD, rh - 2 * TILE_PAD)


def modal_rect():
    margin = 60
    return (margin, margin, hw.WIDTH - 2 * margin, hw.HEIGHT - 2 * margin)


def point_in_rect(x, y, rect):
    rx, ry, rw, rh = rect
    return rx <= x < rx + rw and ry <= y < ry + rh


def hit_test(x, y, regions):
    """regions: list of (rect, action) tuples. Last-drawn (most specific/on-top)
    wins on overlap, so scan in reverse."""
    for rect, action in reversed(regions):
        if point_in_rect(x, y, rect):
            return action
    return None
