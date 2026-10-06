"""Runs in a fresh process: Settings' static constructor only runs once per process.

argv[1]: "new" (no settings file) | "corrupt" (garbage file) | "v46" (file written by
         4.6.0 with the Insane threading mode)
Prints one JSON line with what Settings observed, after constructing a GrblCore.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from lasergrbl_harness import runtime  # noqa: E402

mode = sys.argv[1]


def v46(data):
    import System
    from LaserGRBL import GrblCore

    data["Current LaserGRBL Version"] = System.Version(4, 6, 0)
    data["Threading Mode"] = GrblCore.ThreadingMode.Insane


if mode == "v46":
    runtime.load(settings_seed=v46)
else:
    runtime.load(settings_bytes=b"not a BinaryFormatter stream" if mode == "corrupt" else None)

from LaserGRBL import GrblCore, Settings  # noqa: E402
from lasergrbl_harness import clr_util as cu  # noqa: E402
from lasergrbl_harness.core_rig import fake_syncro, get_setting  # noqa: E402

keys = sorted(str(k) for k in cu.sget(Settings, "dic").Keys)
GrblCore(fake_syncro(), None, None)  # runs the 4.5.0 threading-mode migration check
print(json.dumps({"is_new": bool(Settings.IsNewFile), "prev": str(Settings.PrevVersion), "keys": keys,
                  "threading": str(get_setting("Threading Mode"))}), flush=True)
if runtime.coverage_enabled():
    runtime.flush_coverage()
os._exit(0)
