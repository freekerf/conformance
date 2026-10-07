"""Large-file comparison: LaserGRBL (C#) and FreeKerf analyze the same synthetic raster.

Usage (from the repository root, after ``make build``):

    FREEKERF_BIN=/path/to/freekerf uv run python scripts/large_file.py [LINES] [RUNS]

The raster is the one of FreeKerf's ``crates/core/freekerf-gcode/benches/analysis.rs``
(rows of 500 lines: one ``G0`` and 499 ``G1 X.. S..``), ``LINES`` long (default 100000).
Every field of the golden JSON must be equal (``stream`` included). Printed times, best
of ``RUNS`` (default 3):

* C# load + analysis: ``GrblFile.LoadFile`` in process (what LaserGRBL does when a file
  is opened);
* C# golden analyzer: the above plus streaming the job through the in-memory fake
  device (``golden.analyze_csharp``; the device is Python, so this is mostly harness);
* FreeKerf: ``freekerf analyze --json`` as a process (parse, analysis, a simulated run of
  the host against its emulator for ``stream``, JSON output).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def raster(lines: int) -> str:
    out = ["G90", "M4"]
    i = 0
    while i < lines:
        row = i // 500
        out.append(f"G0 X0 Y{row // 10}.{row % 10}")
        for c in range(499):
            out.append(f"G1 X{c // 10}.{c % 10} S{(c * 7 + row) % 256}")
        i += 500
    out.append("M5")
    return "\n".join(out) + "\n"


def first_difference(cs: dict, rs: dict):
    """None when every golden field is equal, else (field, index, C# value, FreeKerf value)."""
    for key in sorted(set(cs) | set(rs)):
        a, b = cs.get(key), rs.get(key)
        if a == b:
            continue
        if isinstance(a, list) and isinstance(b, list):
            i = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            return key, i, a[i] if i < len(a) else None, b[i] if i < len(b) else None
        return key, None, a, b
    return None


def best(fn, runs):
    times, result = [], None
    for _ in range(runs):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return min(times), result


def main() -> int:
    lines = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    runs = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from lasergrbl_harness import bootstrap

    bootstrap.load_csharp()
    bootstrap.reset_csharp_state()
    from lasergrbl_harness.golden import CONFIG, analyze_csharp, analyze_rust
    from lasergrbl_harness.host import freekerf_bin

    tmp = Path(tempfile.mkdtemp())
    path = tmp / "raster.nc"
    path.write_text(raster(lines))
    print(f"file: {sum(1 for _ in path.open())} lines, {path.stat().st_size / 1e6:.1f} MB")

    import System
    from LaserGRBL import GrblConfST, GrblCore, GrblFile

    from lasergrbl_harness.core_rig import load_file_sync

    table = System.Collections.Generic.Dictionary[int, str]()
    for k, v in CONFIG.items():
        table[k] = v
    GrblCore.Configuration = GrblConfST(GrblCore.GrblVersionInfo(1, 1, "f"), table)

    def cs_load():
        f = GrblFile()
        load_file_sync(f, str(path))
        return f.Count

    t_cs_load, count = best(cs_load, runs)
    t_cs_golden, cs = best(lambda: analyze_csharp(str(path)), 1)
    t_rs, rs = best(lambda: analyze_rust(str(path)), runs)
    diff = first_difference(cs, rs)
    print(f"commands: {count}; stream: {len(cs['stream'])} lines")
    print(f"C# load + analysis (GrblFile.LoadFile): {t_cs_load:.2f} s (best of {runs})")
    print(f"C# golden analyzer (load + analysis + stream through the fake): {t_cs_golden:.2f} s (1 run)")
    print(f"FreeKerf `{os.path.basename(freekerf_bin())} analyze --json` ({freekerf_bin()}): {t_rs:.2f} s (best of {runs})")
    print("equal: yes" if diff is None else f"equal: NO, first difference {diff[0]}[{diff[1]}]: {diff[2]!r} != {diff[3]!r}")
    print(f"estimated time: C# {cs['estimated_time_s']} s, FreeKerf {rs['estimated_time_s']} s")
    sys.stdout.flush()
    os._exit(0 if diff is None else 1)


if __name__ == "__main__":
    main()
