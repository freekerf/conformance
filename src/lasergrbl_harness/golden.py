"""Golden snapshots: G-code file in -> what the host makes of it.

``analyze(path)`` returns a JSON-able dict that a future Rust implementation must
reproduce (via its own adapter returning the same structure):

* ``commands``   command text after loading and analysis (normalized, comments removed)
* ``wire``       the bytes each command puts on the serial line (without "\\n")
* ``stream``     every line a Grbl device receives for a full job run with the
                 default header/footer
* ``offsets_s``  cumulative estimated time at the end of each command (seconds, ms resolution)
* ``estimated_time_s``, ``drawing_range``, ``moving_range`` ([xmin, ymin, xmax, ymax]
  or null), ``spindle_range`` ({min, max, valid} or null), ``quadrant``

The machine configuration used for timing is fixed (CONFIG).
"""

from __future__ import annotations

import os

CONFIG = {110: "6000", 111: "6000", 130: "400", 131: "300", 30: "1000", 32: "1"}


def _num(d) -> float:
    return round(float(str(d)), 6)


def _xy(r):
    if not r.ValidRange:
        return None
    return [_num(r.X.Min), _num(r.Y.Min), _num(r.X.Max), _num(r.Y.Max)]


def analyze_csharp(path: str) -> dict:
    import System
    from LaserGRBL import GrblConfST, GrblCore, Settings

    from .core_rig import CoreRig, MacStatus, load_file_sync

    d = System.Collections.Generic.Dictionary[int, str]()
    for k, v in CONFIG.items():
        d[k] = v
    GrblCore.Configuration = GrblConfST(GrblCore.GrblVersionInfo(1, 1, "f"), d)
    Settings.SetObject("Last GrblVersion known", GrblCore.GrblVersionInfo(1, 1, "f"))

    rig = CoreRig()
    try:
        rig.open_stepped(MacStatus.Idle)
        f = rig.core.LoadedFile
        load_file_sync(f, path)
        cmds = list(f)
        s = f.Range.SpindleRange.S
        out = {
            "input": os.path.basename(path),
            "commands": [str(c.Command) for c in cmds],
            "wire": [str(c.SerialData)[:-1] for c in cmds],
            "offsets_s": [round(c.TimeOffset.TotalSeconds, 3) for c in cmds],
            "estimated_time_s": round(f.EstimatedTime.TotalSeconds, 3),
            "drawing_range": _xy(f.Range.DrawingRange),
            "moving_range": _xy(f.Range.MovingRange),
            "spindle_range": None if s.Min == System.Decimal.MaxValue else
            {"min": _num(s.Min), "max": _num(s.Max), "valid": bool(s.ValidRange)},
            "quadrant": str(f.Quadrant),
        }
        rig.core.RunProgram(None)
        rig.pump()
        out["stream"] = list(rig.device.lines)
        return out
    finally:
        rig.close()


def analyze(path: str) -> dict:
    kind = os.environ.get("LASERGRBL_HOST", "csharp")
    if kind == "csharp":
        return analyze_csharp(path)
    raise RuntimeError(f"no golden analyzer for LASERGRBL_HOST={kind!r}")
