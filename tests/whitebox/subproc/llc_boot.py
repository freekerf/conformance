"""Fresh process: LaserLifeHandler's static constructor with a pre-existing counter file.

argv[1]: "main" (LaserLifeCounter.bin) | "old" (only LaserLifeCounter.bin.old) | "empty" (file with an empty list)
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "src"))
from lasergrbl_harness import runtime  # noqa: E402

runtime.load()
import System  # noqa: E402
from LaserGRBL import GrblCore  # noqa: E402
from Tools import Serializer  # noqa: E402
import LaserGRBL  # noqa: E402

LLH = getattr(LaserGRBL, "LaserLifeHandler")
mode = sys.argv[1]
lst = LLH.ListLLC()
if mode != "empty":
    c = LLH.LaserLifeCounter.CreateDefault()
    c.Name = "from-" + mode
    lst.Add(c)
name = os.path.join(str(GrblCore.DataPath), "LaserLifeCounter.bin" + (".old" if mode == "old" else ""))
Serializer.ObjToFile(lst, name)
names = [str(c.Name) for c in LLH.GetListClone()]  # first use runs the static constructor
print(json.dumps({"names": names}), flush=True)
if runtime.coverage_enabled():
    runtime.flush_coverage()
os._exit(0)
