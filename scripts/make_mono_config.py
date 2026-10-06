#!/usr/bin/env python3
"""Writes a Mono global config = system config + entries routed to native/lgshim.c.

* kernel32 timer functions (Tools.HiResTimer). The system /etc/mono/config already
  maps `i:kernel32.dll` (to __Internal, for a few memory functions) and that mapping
  wins over per-assembly configs, so the entries go into that element of the
  *global* config.
* MonoPosixHelper!set_signal, so Mono's SerialPort can open a PTY.

Usage: make_mono_config.py <out-config> <path/to/liblgshim.so>
"""
import os
import sys
import xml.etree.ElementTree as ET

out, shim = sys.argv[1], sys.argv[2]
src = os.environ.get("MONO_SYSTEM_CONFIG", "/etc/mono/config")
# $mono_libdir is only expanded for the default config location, so resolve it here
libdir = os.environ.get("MONO_LIBDIR") or next(
    (d for d in ("/usr/lib", "/usr/lib64", "/usr/local/lib") if os.path.exists(os.path.join(d, "libmono-native.so"))),
    "/usr/lib",
)
root = ET.fromstring(open(src).read().replace("$mono_libdir", libdir))
tree = ET.ElementTree(root)

k32 = next((m for m in root.findall("dllmap") if m.get("dll", "").lower() == "i:kernel32.dll"), None)
if k32 is None:
    k32 = ET.SubElement(root, "dllmap", {"dll": "i:kernel32.dll"})
for name in ("QueryPerformanceCounter", "QueryPerformanceFrequency", "GetTickCount"):
    ET.SubElement(k32, "dllentry", {"dll": shim, "name": name, "target": name})

# Function-level map in its own element, placed *first* in the document: Mono resolves
# the library of every MonoPosixHelper function from the first matching map entry
# that has a target, and entries end up in reverse document order.
posix = ET.Element("dllmap", {"dll": "MonoPosixHelper"})
ET.SubElement(posix, "dllentry", {"dll": shim, "name": "set_signal", "target": "lg_set_signal"})
root.insert(0, posix)
tree.write(out, encoding="unicode", xml_declaration=False)  # Mono's config parser rejects an XML declaration
