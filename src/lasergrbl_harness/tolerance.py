"""Tolerance for the ``platform_dependent`` importer cases, used for the Rust host only.

Those goldens were drawn by libgdiplus (Mono's GDI+), whose rounding and interpolation
differ from Windows GDI+ and from FreeKerf. FreeKerf ADR 0008 defines the metric; the
C# host is always compared exactly.

Bitmaps (``pixels``, rows of ``AARRGGBB`` tokens): same size, and over every channel
of every pixel the absolute difference is at most ``PIXEL_MAX_DELTA`` and its mean at
most ``PIXEL_MEAN_DELTA`` (0..255 scale).
"""

from __future__ import annotations

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
