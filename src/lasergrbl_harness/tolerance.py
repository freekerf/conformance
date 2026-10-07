"""Tolerance for the ``platform_dependent`` importer cases, used for the Rust host only.

Those goldens were drawn by libgdiplus (Mono's GDI+), whose rounding and interpolation
differ from Windows GDI+ and from FreeKerf. FreeKerf ADR 0008 defines the metric; the
C# host is always compared exactly.

Bitmaps (``pixels``, rows of ``AARRGGBB`` tokens): same size, and over every channel
of every pixel the absolute difference is at most ``PIXEL_MAX_DELTA`` and its mean at
most ``PIXEL_MEAN_DELTA`` (0..255 scale).

G-code (``gcode`` of cases drawn through GDI+ before engraving): the lines before
the first and after the last move are equal; every cutting move is drawn onto a grid
of the job's resolution (``cell`` mm), each cell keeping the highest power that
crossed it on a 0..255 scale, and the two maps are compared with the bitmap metric,
allowing a one-cell shift for the maximum. ``summary``: ranges within one cell,
estimated time within 5 %.
"""

from __future__ import annotations

import math
import re

PIXEL_MAX_DELTA = 8
PIXEL_MEAN_DELTA = 1.5


def _channels(rows):
    out = []
    for row in rows:
        r = []
        for tok in row.split():
            v = int(tok, 16)
            r.append(((v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255))
        out.append(r)
    return out


def pixel_difference(got, expected):
    """``(max, mean)`` channel difference of two dumps, or ``None`` if their sizes differ."""
    a, b = _channels(got), _channels(expected)
    if len(a) != len(b) or any(len(x) != len(y) for x, y in zip(a, b)):
        return None
    deltas = [abs(p - q) for ra, rb in zip(a, b) for pa, pb in zip(ra, rb) for p, q in zip(pa, pb)]
    if not deltas:
        return (0, 0.0)
    return (max(deltas), sum(deltas) / len(deltas))


def pixels_within_tolerance(got, expected):
    """True if two bitmap dumps are equal within the ADR 0008 tolerance."""
    if not isinstance(got, list) or not isinstance(expected, list):
        return False
    d = pixel_difference(got, expected)
    return d is not None and d[0] <= PIXEL_MAX_DELTA and d[1] <= PIXEL_MEAN_DELTA


# ---------------------------------------------------------------- G-code (burn maps)

GCODE_MAX_DELTA = PIXEL_MAX_DELTA
GCODE_MEAN_DELTA = PIXEL_MEAN_DELTA
TIME_RELATIVE = 0.05

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")


def _moves(lines):
    """Cutting moves of a program: ``(x0, y0, x1, y1, power, arc)`` in mm, with
    ``arc`` = (i, j, clockwise) or None. Absolute coordinates (G90, LaserGRBL's)
    unless G91; the laser burns between M3/M4 and M5, at the last S."""
    x = y = 0.0
    s = 0.0
    on = False
    motion = 0
    relative = False
    out = []
    for line in lines:
        text = re.sub(r"\([^)]*\)|;.*", "", line).upper()
        words = _WORD.findall(text)
        coords = {}
        for letter, value in words:
            v = float(value)
            if letter == "G":
                g = int(v)
                if g in (0, 1, 2, 3):
                    motion = g
                elif g == 90:
                    relative = False
                elif g == 91:
                    relative = True
            elif letter == "M":
                m = int(v)
                if m in (3, 4):
                    on = True
                elif m == 5:
                    on = False
            elif letter == "S":
                s = v
            else:
                coords[letter] = v
        if "X" not in coords and "Y" not in coords:
            continue
        nx = coords.get("X", 0.0 if relative else x) + (x if relative else 0.0)
        ny = coords.get("Y", 0.0 if relative else y) + (y if relative else 0.0)
        if motion != 0 and on and s > 0:
            arc = (coords.get("I", 0.0), coords.get("J", 0.0), motion == 2) if motion in (2, 3) else None
            out.append((x, y, nx, ny, s, arc))
        x, y = nx, ny
    return out


def _samples(move, step):
    x0, y0, x1, y1, _, arc = move
    if arc is None:
        n = max(1, int(math.hypot(x1 - x0, y1 - y0) / step) + 1)
        return [(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n) for k in range(n + 1)]
    i, j, cw = arc
    cx, cy = x0 + i, y0 + j
    r = math.hypot(i, j)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if cw and sweep >= 0:
        sweep -= 2 * math.pi
    if not cw and sweep <= 0:
        sweep += 2 * math.pi
    n = max(1, int(abs(sweep) * r / step) + 1)
    return [(cx + r * math.cos(a0 + sweep * k / n), cy + r * math.sin(a0 + sweep * k / n)) for k in range(n + 1)]


def burn_map(lines, cell, scale):
    """``{(col, row): level}``: every cell a cutting move crosses, with the highest
    power that crossed it, as 0..255 of ``scale`` (the highest power of both
    programs compared)."""
    cells = {}
    for move in _moves(lines):
        level = min(255.0, 255.0 * move[4] / scale) if scale > 0 else 0.0
        for px, py in _samples(move, cell / 4):
            key = (math.floor(px / cell + 1e-9), math.floor(py / cell + 1e-9))
            if cells.get(key, 0.0) < level:
                cells[key] = level
    return cells


def _max_power(lines):
    return max((m[4] for m in _moves(lines)), default=0.0)


def gcode_difference(got, expected, cell):
    """``(max, mean)`` of two burn maps: the maximum allows each burned cell to be
    matched by one of its 8 neighbours (a one-cell shift), the mean compares cell by
    cell over the cells either program burns."""
    scale = max(_max_power(got), _max_power(expected))
    a, b = burn_map(got, cell, scale), burn_map(expected, cell, scale)
    keys = set(a) | set(b)
    if not keys:
        return (0.0, 0.0)

    def near(m, other, key):
        cx, cy = key
        return min(abs(m.get(key, 0.0) - other.get((cx + dx, cy + dy), 0.0)) for dx in (-1, 0, 1) for dy in (-1, 0, 1))

    worst = max(max(near(a, b, k) for k in keys), max(near(b, a, k) for k in keys))
    mean = sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in keys) / len(keys)
    return (worst, mean)


def _edges(lines):
    """The lines before the first and after the last cutting move."""
    moving = [i for i, line in enumerate(lines) if re.match(r"^\s*(G0*[123]\b|[XY])", line, re.I)]
    if not moving:
        return (list(lines), [])
    return (list(lines[: moving[0]]), list(lines[moving[-1] + 1 :]))


def gcode_within_tolerance(got, expected, cell):
    """True if two programs burn the same within the ADR 0008 tolerance: same lines
    before the first and after the last move, burn maps within the bitmap metric."""
    if not isinstance(got, list) or not isinstance(expected, list):
        return False
    if _edges(got) != _edges(expected):
        return False
    worst, mean = gcode_difference(got, expected, cell)
    return worst <= GCODE_MAX_DELTA and mean <= GCODE_MEAN_DELTA


def summary_within_tolerance(got, expected, cell):
    """Ranges within one cell, estimated time within 5 %; the command count is not
    compared (equal burns can be split in more or fewer lines)."""
    if not isinstance(got, dict) or not isinstance(expected, dict):
        return False
    for key in ("drawing_range", "moving_range"):
        g, e = got.get(key), expected.get(key)
        if (g is None) != (e is None):
            return False
        if g is not None and any(abs(p - q) > cell + 1e-9 for p, q in zip(g, e)):
            return False
    te, tg = expected.get("estimated_time_s", 0.0), got.get("estimated_time_s", 0.0)
    return abs(tg - te) <= TIME_RELATIVE * max(abs(te), 1e-9)
