"""Host adapters for the black-box protocol tests.

A protocol test only (1) drives a *host* through the small ``HostAdapter`` API and
(2) asserts on what the fake Grbl device saw on the serial line (plus a few coarse
host states). The current host is the C# GrblCore talking to a PTY through its own
``UsbSerial`` wrapper (``CSharpHost``). A Rust implementation only needs another
adapter with the same methods (e.g. driving the new binary over a CLI or IPC) for
the whole ``tests/protocol`` suite to run against it.

Select the adapter with ``LASERGRBL_HOST`` (default ``csharp``): ``csharp`` is the
LaserGRBL core in-process (Mono), ``rust`` is FreeKerf's ``freekerf host --stdio``
(binary from ``FREEKERF_BIN``, default ``freekerf`` on the PATH).
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


def freekerf_bin() -> str:
    """Path of the FreeKerf binary (``FREEKERF_BIN``, default ``freekerf``)."""
    return os.environ.get("FREEKERF_BIN", "freekerf")


class RustHostError(RuntimeError):
    """An action of the Rust host failed."""


class RustHost:
    """FreeKerf (Rust) as the host: ``freekerf host --stdio`` in a subprocess.

    Every adapter call is one action of FreeKerf's registry, sent as a JSON line
    (``{"id", "action", "params"}``) and answered with ``{"id", "ok", "result"|"error"}``
    (protocol: ``doc/features/host-protocol.md`` in the freekerf repository). Settings
    live in memory, so every host starts from the defaults.
    """

    OPTIONS = {
        "streaming_mode": "machine.streaming_mode",
        "reset_on_connect": "machine.reset_on_connect",
        "query_machine_info": "machine.query_machine_info",
        "continuous_jog": "machine.continuous_jog",
    }

    # LaserGRBL silently ignores these when the state does not allow them
    # (feed hold while idle, unlock while running...): so does the adapter.
    FIRE_AND_FORGET = {"machine.feed_hold", "machine.resume", "machine.unlock", "machine.home",
                       "job.abort", "machine.jog"}

    def __init__(self):
        import subprocess
        import threading

        self._proc = subprocess.Popen(
            [freekerf_bin(), "host", "--stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()
        self._next = 0

    def _call(self, action, params=None):
        import json

        with self._lock:
            self._next += 1
            req = {"id": self._next, "action": action, "params": params}
            self._proc.stdin.write(json.dumps(req) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
        if not line:
            raise RustHostError(f"{action}: freekerf exited")
        resp = json.loads(line)
        if resp.get("ok"):
            return resp.get("result")
        err = resp.get("error") or {}
        if err.get("kind") == "refused" and action in self.FIRE_AND_FORGET:
            return None
        raise RustHostError(f"{action}: {err.get('message', err)}")

    def _state(self):
        return self._call("state.get")

    # connection
    def connect(self, port, baud=115200):
        self._call("machine.connect", {"port": port, "baud": baud})

    def disconnect(self):
        self._call("machine.disconnect")

    def set_option(self, name, value):
        self._call("settings.set", {"key": self.OPTIONS[name], "value": value})

    # job
    def load_gcode(self, path):
        self._call("job.load", {"path": str(path)})

    def run_job(self):
        self._call("job.run")

    def abort_job(self):
        self._call("job.abort")

    # immediate / manual
    def send_command(self, line):
        self._call("machine.send", {"line": line})

    def feed_hold(self):
        self._call("machine.feed_hold")

    def resume(self):
        self._call("machine.resume")

    def soft_reset(self):
        self._call("machine.stop")

    def unlock(self):
        self._call("machine.unlock")

    def home(self):
        self._call("machine.home")

    def jog(self, direction, step, feed):
        self._call("machine.jog", {"direction": direction, "step_mm": float(step), "feed_mm_min": float(feed)})

    def set_override_targets(self, feed, rapid, spindle):
        self._call("machine.overrides", {"feed": feed, "rapid": rapid, "power": spindle})

    def write_settings(self, settings):
        self._call("machine.write_settings", {"settings": {str(k): str(v) for k, v in settings.items()}})

    # observation
    @property
    def status(self):
        return self._state()["machine"]["status"]

    @property
    def connected(self):
        return bool(self._state()["machine"]["connected"])

    @property
    def ready(self):
        return bool(self._state()["machine"]["ready"])

    @property
    def job_running(self):
        return bool(self._state()["machine"]["in_program"])

    @property
    def issues(self):
        return list(self._state()["issues"])

    @property
    def firmware_version(self):
        return self._state()["firmware_version"]

    @property
    def job_errors(self):
        return int(self._state()["machine"]["job_errors"])

    def close(self):
        if self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=10)
            except Exception:
                self._proc.kill()
                self._proc.wait()


def make_host() -> HostAdapter:
    kind = os.environ.get("LASERGRBL_HOST", "csharp")
    if kind == "csharp":
        return CSharpHost()
    if kind == "rust":
        return RustHost()
    raise RuntimeError(f"unknown LASERGRBL_HOST={kind!r} (csharp or rust)")
