"""Host adapters for the black-box protocol tests.

A protocol test only (1) drives a *host* through the small ``HostAdapter`` API and
(2) asserts on what the fake Grbl device saw on the serial line (plus a few coarse
host states). The current host is the C# GrblCore talking to a PTY through its own
``UsbSerial`` wrapper (``CSharpHost``). A Rust implementation only needs another
adapter with the same methods (e.g. driving the new binary over a CLI or IPC) for
the whole ``tests/protocol`` suite to run against it.

Select the adapter with ``LASERGRBL_HOST`` (default ``csharp``).
"""

from __future__ import annotations

import os
import time
from typing import Protocol


class HostAdapter(Protocol):
    # connection
    def connect(self, port: str, baud: int = 115200) -> None: ...
    def disconnect(self) -> None: ...

    # options that change the wire behaviour
    def set_option(self, name: str, value) -> None: ...

    # job
    def load_gcode(self, path: str) -> None: ...
    def run_job(self) -> None: ...
    def abort_job(self) -> None: ...

    # immediate / manual
    def send_command(self, line: str) -> None: ...
    def feed_hold(self) -> None: ...
    def resume(self) -> None: ...
    def soft_reset(self) -> None: ...
    def unlock(self) -> None: ...
    def home(self) -> None: ...
    def jog(self, direction: str, step: float, feed: int) -> None: ...
    def set_override_targets(self, feed: int, rapid: int, spindle: int) -> None: ...
    def write_settings(self, settings: dict[int, str]) -> None: ...

    # observation
    @property
    def status(self) -> str: ...
    @property
    def connected(self) -> bool: ...
    @property
    def ready(self) -> bool:
        """Connected and done with connect-time housekeeping (settings/info queries)."""
        ...
    @property
    def job_running(self) -> bool: ...
    @property
    def issues(self) -> list[str]: ...
    @property
    def firmware_version(self) -> str | None: ...
    @property
    def job_errors(self) -> int: ...

    def close(self) -> None: ...


def _core_types():
    from LaserGRBL import GrblCore

    return GrblCore


def wait(predicate, timeout: float = 10.0, message: str = "", interval: float = 0.005) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(message or f"condition not met in {timeout}s")
        time.sleep(interval)


class CSharpHost:
    """LaserGRBL's GrblCore (C#) as the host; serial I/O through UsbSerial (Mono SerialPort)."""

    OPTIONS = {
        "streaming_mode": ("Streaming Mode", lambda v: getattr(_core_types().StreamingMode, v)),
        "reset_on_connect": ("Reset Grbl On Connect", bool),
        "query_machine_info": ("Query MachineInfo ($I) at connect", bool),
        "continuous_jog": ("Enable Continuous Jog", bool),
    }

    def __init__(self):
        import System
        from LaserGRBL import GrblCore, Settings
        from LaserGRBLTests import EventRecorder

        from .core_rig import fake_syncro

        self._System = System
        self._Settings = Settings
        self.core = GrblCore(fake_syncro(), None, None)
        self.recorder = EventRecorder(self.core)

    def set_option(self, name, value):
        key, conv = self.OPTIONS[name]
        self._Settings.SetObject(key, conv(value))

    def connect(self, port, baud=115200):
        from LaserGRBL.ComWrapper import WrapperType

        self.core.Configure(WrapperType.UsbSerial, port, self._System.Int32(baud))
        self.core.OpenCom()

    def disconnect(self):
        self.core.CloseCom(True)

    def load_gcode(self, path):
        from .core_rig import load_file_sync

        load_file_sync(self.core.LoadedFile, path)

    def run_job(self):
        self.core.RunProgram(None)

    def abort_job(self):
        self.core.AbortProgram()

    def send_command(self, line):
        from LaserGRBL import GrblCommand

        self.core.EnqueueCommand(GrblCommand(line))

    def feed_hold(self):
        self.core.FeedHold(False)

    def resume(self):
        self.core.CycleStartResume(False)

    def soft_reset(self):
        self.core.GrblReset()

    def unlock(self):
        from . import clr_util as cu

        cu.call(self.core, "GrblUnlock")

    def home(self):
        from . import clr_util as cu

        cu.call(self.core, "GrblHoming")

    def jog(self, direction, step, feed):
        from LaserGRBL import GrblCore

        d = getattr(GrblCore.JogDirection, direction)
        self.core.JogToDirection(d, float(feed), self._System.Decimal(step))

    def set_override_targets(self, feed, rapid, spindle):
        self.core.TOverrideG1, self.core.TOverrideG0, self.core.TOverrideS = feed, rapid, spindle

    def write_settings(self, settings):
        from LaserGRBL import GrblConfST

        lst = self._System.Collections.Generic.List[GrblConfST.GrblConfParam]()
        for k, v in settings.items():
            lst.Add(GrblConfST.GrblConfParam(k, str(v)))
        self.core.WriteConfig(lst)

    @property
    def status(self):
        return str(self.core.MachineStatus)

    @property
    def connected(self):
        return bool(self.core.IsConnected)

    @property
    def ready(self):
        # the connect-time $$/$I refresh swaps the core's queue pointers; anything
        # queued while they are swapped is lost (FINDINGS.md F-30)
        import System

        from . import clr_util as cu

        c = self.core
        return (self.connected
                and System.Object.ReferenceEquals(cu.get(c, "mQueuePtr"), cu.get(c, "mQueue"))
                and System.Object.ReferenceEquals(cu.get(c, "mSentPtr"), cu.get(c, "mSent"))
                and cu.get(c, "mPending").Count == 0)

    @property
    def job_running(self):
        return bool(self.core.InProgram)

    @property
    def issues(self):
        return [str(e)[6:] for e in self.recorder.Snapshot() if str(e).startswith("issue:")]

    @property
    def firmware_version(self):
        v = self.core.GrblVersion
        return None if v is None else str(v)

    @property
    def job_errors(self):
        from . import clr_util as cu

        return int(cu.get(cu.get(self.core, "mTP"), "mErrorCount"))

    def close(self):
        from . import clr_util as cu

        try:
            self.core.CloseCom(True)
        except Exception:
            pass
        for name in ("TX", "RX"):
            try:
                cu.get(self.core, name).Stop()
            except Exception:
                pass


def make_host() -> HostAdapter:
    kind = os.environ.get("LASERGRBL_HOST", "csharp")
    if kind == "csharp":
        return CSharpHost()
    raise RuntimeError(f"unknown LASERGRBL_HOST={kind!r} (only 'csharp' exists today)")
