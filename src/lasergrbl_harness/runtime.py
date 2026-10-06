"""Loads LaserGRBL.exe into this Python process through pythonnet on the Mono runtime.

Everything that must happen *before* the CLR starts lives here:

* an isolated HOME/XDG_CONFIG_HOME, so ``GrblCore.DataPath`` (``~/.config/LaserGRBL``)
  and ``LaserGRBL.Settings.bin`` never touch the user's real settings;
* no DISPLAY, so any accidental WinForms usage fails fast instead of opening windows;
* ``MONO_CONFIG`` pointing at the generated global config that routes the kernel32
  timer P/Invokes used by ``Tools.HiResTimer`` to our native shim
  (see ``scripts/build_lasergrbl.sh`` and ``native/k32shim.c``).

Environment variables:

``LASERGRBL_BUILD_DIR``  build work dir (default ``~/.cache/freekerf-conformance/build``)
``LASERGRBL_BIN_DIR``    directory holding the LaserGRBL.exe to load
                         (default ``$LASERGRBL_BUILD_DIR/src/LaserGRBL/bin/Debug``)
``LASERGRBL_COVERAGE``   ``1`` when the exe in LASERGRBL_BIN_DIR is AltCover-instrumented;
                         the recorder is flushed at interpreter exit.
"""

from __future__ import annotations

import atexit
import os
import sys
import tempfile
from pathlib import Path

_loaded = False
HOME: Path | None = None
_REAL_HOME = Path.home()  # captured before load() points HOME to a temp dir


def build_dir() -> Path:
    return Path(os.environ.get("LASERGRBL_BUILD_DIR", _REAL_HOME / ".cache" / "freekerf-conformance" / "build"))


def bin_dir() -> Path:
    env = os.environ.get("LASERGRBL_BIN_DIR")
    return Path(env) if env else build_dir() / "src" / "LaserGRBL" / "bin" / "Debug"


def coverage_enabled() -> bool:
    return os.environ.get("LASERGRBL_COVERAGE") == "1"


def _seed_settings(home: Path, seed) -> None:
    """Optionally pre-create LaserGRBL.Settings.bin before Settings' static ctor runs.

    ``seed`` is a callable receiving the (CLR) Dictionary[str, object] to fill.
    """
    import System
    from System.Collections.Generic import Dictionary
    from System.IO import FileMode, FileStream
    from System.Runtime.Serialization.Formatters.Binary import BinaryFormatter

    data = Dictionary[System.String, System.Object]()
    seed(data)
    datapath = home / ".config" / "LaserGRBL"
    datapath.mkdir(parents=True, exist_ok=True)
    fs = FileStream(str(datapath / "LaserGRBL.Settings.bin"), FileMode.Create)
    try:
        BinaryFormatter().Serialize(fs, data)
    finally:
        fs.Close()


def is_loaded() -> bool:
    return _loaded


def load(settings_seed=None, settings_bytes: bytes | None = None) -> None:
    """Start the CLR and add the LaserGRBL assembly. Idempotent.

    ``settings_seed(dict)`` pre-fills LaserGRBL.Settings.bin through BinaryFormatter;
    ``settings_bytes`` writes that file verbatim (e.g. a corrupt file).
    """
    global _loaded, HOME
    if _loaded:
        return

    exe = bin_dir() / "LaserGRBL.exe"
    if not exe.exists():
        raise RuntimeError(f"{exe} not found - run `make build` first")
    mono_config = build_dir() / "mono-config"
    if not mono_config.exists():
        raise RuntimeError(f"{mono_config} not found - run `make build` first")

    # child processes (subprocess-based tests) inherit the resolved locations
    os.environ["LASERGRBL_BUILD_DIR"] = str(build_dir())
    os.environ["LASERGRBL_BIN_DIR"] = str(exe.parent)

    HOME = Path(tempfile.mkdtemp(prefix="lasergrbl-home-"))
    os.environ["HOME"] = str(HOME)
    os.environ["XDG_CONFIG_HOME"] = str(HOME / ".config")
    os.environ["XDG_DATA_HOME"] = str(HOME / ".local" / "share")
    os.environ.pop("DISPLAY", None)
    os.environ.pop("WAYLAND_DISPLAY", None)
    os.environ["MONO_CONFIG"] = str(mono_config)
    # deterministic CurrentCulture (Mono derives it from the locale); tests that care
    # about culture-dependent parsing set Thread.CurrentCulture explicitly
    os.environ["LANG"] = os.environ["LC_ALL"] = "C"
    # Mono raises NullReferenceException from a SIGSEGV handler; inside a Python process
    # other handlers (faulthandler) can intercept that signal. Explicit null checks
    # make the JIT throw NREs without signals.
    os.environ["MONO_DEBUG"] = ",".join(filter(None, [os.environ.get("MONO_DEBUG"), "explicit-null-checks"]))

    import warnings

    import pythonnet

    with warnings.catch_warnings():
        # clr_loader warns about Mono < 6.12; 6.8 works for this use (see README)
        warnings.simplefilter("ignore")
        pythonnet.load("mono")
    import clr

    sys.path.append(str(exe.parent))
    clr.AddReference(str(exe))
    clr.AddReference(str(exe.parent / "TestSupport.dll"))  # tools/TestSupport.cs
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    clr.AddReference("WindowsBase")

    if settings_seed is not None:
        _seed_settings(HOME, settings_seed)
    elif settings_bytes is not None:
        datapath = HOME / ".config" / "LaserGRBL"
        datapath.mkdir(parents=True, exist_ok=True)
        (datapath / "LaserGRBL.Settings.bin").write_bytes(settings_bytes)

    if coverage_enabled():
        clr.AddReference(str(exe.parent / "AltCover.Recorder.g.dll"))
        atexit.register(flush_coverage)  # for non-pytest users; the pytest hook flushes explicitly

    _loaded = True


_flushed = False


def flush_coverage() -> None:
    """Write the AltCover visit counts into the coverage report (once per process)."""
    global _flushed
    if _flushed:
        return
    _flushed = True
    from AltCover.Recorder import Instance  # type: ignore

    Instance.FlushFinish()
