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
    def run_job(self, homing: bool = False, passes: int = 1) -> None: ...
    def resume_job(self, position: int, homing: bool = False, set_wco: bool = False) -> None:
        """Run the loaded program from ``position`` (0-based), rebuilding position and modes."""
        ...
    def abort_job(self) -> None: ...

    # immediate / manual
    def send_command(self, line: str) -> None: ...
    def custom_code(self, code: str) -> None:
        """Custom button code: lines separated by newlines, ``[expr]`` evaluated,
        immediate characters (``!``, ``~``, ``?``, ``ctrl-x``, ``0xNN``) sent at once."""
        ...
    def feed_hold(self) -> None: ...
    def resume(self) -> None: ...
    def safety_door(self) -> None: ...
    def soft_reset(self) -> None: ...
    def unlock(self) -> None: ...
    def home(self) -> None: ...
    def set_zero(self) -> None: ...
    def jog(self, direction: str, step: float, feed: int) -> None: ...
    def jog_to(self, x: float, y: float, feed: int) -> None: ...
    def jog_abort(self) -> None: ...
    def set_override_targets(self, feed: int, rapid: int, spindle: int) -> None: ...
    def write_settings(self, settings: dict[int, str]) -> None: ...
    def refresh_settings(self) -> None:
        """Read the board settings again (``$$``); returns when they were read."""
        ...

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
    @property
    def firmware_vendor(self) -> str | None:
        """Vendor/model seen before or in the banner (Ortur, Longer, Grbl-Vigo...)."""
        ...
    @property
    def machine_position(self) -> tuple[float, float, float]: ...
    @property
    def work_offset(self) -> tuple[float, float, float]: ...
    @property
    def overrides(self) -> tuple[int, int, int]:
        """Overrides reported by the board (feed, rapids, spindle)."""
        ...
    @property
    def buffer_size(self) -> int:
        """RX buffer size the host streams against."""
        ...
    @property
    def detected_ip(self) -> str | None: ...
    @property
    def last_issue(self) -> str:
        """Why the last job stopped (``Unknown`` when it did not stop early)."""
        ...

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
    """LaserGRBL's GrblCore (C#) as the host; serial I/O through UsbSerial (Mono SerialPort).

    Calls go to what the LaserGRBL UI calls (buttons, menus, dialogs once confirmed);
    the few internal methods used (``ContinueProgramFromKnown``, ``ExecuteCustomCode``,
    ``SetNewZero``...) are the ones those UI paths end in, with the same guards."""

    OPTIONS = {
        "streaming_mode": ("Streaming Mode", lambda v: getattr(_core_types().StreamingMode, v)),
        "reset_on_connect": ("Reset Grbl On Connect", bool),
        "query_machine_info": ("Query MachineInfo ($I) at connect", bool),
        "continuous_jog": ("Enable Continuous Jog", bool),
        "custom_header": ("GCode.CustomHeader", str),
        "custom_footer": ("GCode.CustomFooter", str),
        "custom_passes": ("GCode.CustomPasses", str),
        "support_pwm": ("Support Hardware PWM", bool),
    }
    # GrblCore subclass per "Firmware Type"
    FIRMWARES = {"Grbl": "GrblCore", "Smoothie": "SmoothieCore", "Marlin": "MarlinCore", "VigoWork": "VigoCore"}

    def __init__(self):
        import System
        from LaserGRBL import Settings

        self._System = System
        self._Settings = Settings
        self._make_core("GrblCore")

    def _make_core(self, cls_name):
        import LaserGRBL
        from LaserGRBLTests import EventRecorder

        from .core_rig import fake_syncro

        self.core = getattr(LaserGRBL, cls_name)(fake_syncro(), None, None)
        self.recorder = EventRecorder(self.core)

    def set_option(self, name, value):
        if name == "firmware":
            # LaserGRBL builds the core for the configured firmware at startup
            from LaserGRBL import Firmware

            self._Settings.SetObject("Firmware Type", getattr(Firmware, value))
            self._make_core(self.FIRMWARES[value])
            return
        if name == "auto_cooling":  # None or (on_s, off_s)
            ts = self._System.TimeSpan
            self._Settings.SetObject("AutoCooling", value is not None)
            if value is not None:
                self._Settings.SetObject("AutoCooling TOn", ts.FromSeconds(value[0]))
                self._Settings.SetObject("AutoCooling TOff", ts.FromSeconds(value[1]))
            return
        if name == "jog_step":  # used by [jogstep] in custom code (the jog panel value)
            self.core.JogStep = self._System.Decimal(value)
            return
        if name == "jog_speed":
            self.core.JogSpeed = int(value)
            return
        key, conv = self.OPTIONS[name]
        if conv is str:
            # custom code is split on Environment.NewLine (CRLF on Windows)
            value = self._System.Environment.NewLine.join(str(value).split("\n"))
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

    def run_job(self, homing=False, passes=1):
        from . import clr_util as cu

        self.core.LoopCount = self._System.Decimal(passes)
        if homing:
            # LaserGRBL homes before a job only from the resume dialog (position 0),
            # which also skips the header (F-54); this is the start of a new job with
            # homing, as pinned by test_run_from_start_with_homing_pushes_dollar_h_first
            if self.core.CanSendFile:
                cu.call(self.core, "RunProgramFromStart", True, True, False)
            return
        self.core.RunProgram(None)

    def resume_job(self, position, homing=False, set_wco=False):
        from . import clr_util as cu

        # RunProgramFromPosition / the resume dialog, once confirmed
        if self.core.CanSendFile:
            cu.call(self.core, "ContinueProgramFromKnown", position, homing, set_wco)

    def abort_job(self):
        self.core.AbortProgram()

    def send_command(self, line):
        from LaserGRBL import GrblCommand

        self.core.EnqueueCommand(GrblCommand(line))

    def custom_code(self, code):
        from . import clr_util as cu

        cu.call(self.core, "ExecuteCustomCode", self._System.Environment.NewLine.join(code.split("\n")))

    def feed_hold(self):
        self.core.FeedHold(False)

    def resume(self):
        self.core.CycleStartResume(False)

    def safety_door(self):
        self.core.SafetyDoor()

    def soft_reset(self):
        self.core.GrblReset()

    def unlock(self):
        from . import clr_util as cu

        cu.call(self.core, "GrblUnlock")

    def home(self):
        from . import clr_util as cu

        cu.call(self.core, "GrblHoming")

    def set_zero(self):
        from . import clr_util as cu

        cu.call(self.core, "SetNewZero")

    def jog(self, direction, step, feed):
        from LaserGRBL import GrblCore

        d = getattr(GrblCore.JogDirection, direction)
        self.core.JogToDirection(d, float(feed), self._System.Decimal(step))

    def jog_to(self, x, y, feed):
        from System import Single
        from System.Drawing import PointF

        self.core.JogToPosition.Overloads[PointF, Single](PointF(x, y), float(feed))

    def jog_abort(self):
        self.core.JogAbort()

    def set_override_targets(self, feed, rapid, spindle):
        self.core.TOverrideG1, self.core.TOverrideG0, self.core.TOverrideS = feed, rapid, spindle

    def refresh_settings(self):
        from LaserGRBL import GrblCore

        self.core.RefreshConfig(GrblCore.RefreshCause.OnDialog)

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

    @property
    def firmware_vendor(self):
        v = self.core.GrblVersion
        return None if v is None or v.MachineName is None else str(v.MachineName)

    @staticmethod
    def _point(p):
        return (float(p.X), float(p.Y), float(p.Z))

    @property
    def machine_position(self):
        return self._point(self.core.MachinePosition)

    @property
    def work_offset(self):
        return self._point(self.core.WorkingOffset)

    @property
    def overrides(self):
        c = self.core
        return (int(c.OverrideG1), int(c.OverrideG0), int(c.OverrideS))

    @property
    def buffer_size(self):
        return int(self.core.BufferSize)

    @property
    def detected_ip(self):
        ip = self.core.DetectedIP
        return None if ip is None else str(ip)

    @property
    def last_issue(self):
        from . import clr_util as cu

        return str(cu.get(self.core, "mTP").LastIssue)

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
    """An action of the Rust host failed; ``kind`` is the error kind of the protocol
    (``refused``, ``failed``, ``invalid_params``...)."""

    def __init__(self, message, kind=None):
        super().__init__(message)
        self.kind = kind


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
        "custom_header": "job.header",
        "custom_footer": "job.footer",
        "custom_passes": "job.passes",
        "support_pwm": "machine.support_pwm",
        "firmware": "machine.firmware",
        "jog_step": "jog.step_mm",
        "jog_speed": "jog.speed_mm_min",
    }

    # LaserGRBL silently ignores these when the state does not allow them
    # (feed hold while idle, unlock while running...): so does the adapter.
    FIRE_AND_FORGET = {"machine.feed_hold", "machine.resume", "machine.unlock", "machine.home",
                       "job.abort", "machine.jog", "machine.jog_to", "machine.jog_stop",
                       "machine.set_zero", "machine.safety_door", "job.run", "job.resume"}

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
            raise RustHostError(f"{action}: freekerf exited", "exited")
        resp = json.loads(line)
        if resp.get("ok"):
            return resp.get("result")
        err = resp.get("error") or {}
        # DIV-103: what LaserGRBL silently ignores (state does not allow it, or the
        # firmware has no such command, e.g. unlock on Smoothie) is an error here
        ignored = err.get("kind") == "refused" or str(err.get("message", "")).startswith("not supported")
        if ignored and action in self.FIRE_AND_FORGET:
            return None
        raise RustHostError(f"{action}: {err.get('message', err)}", err.get("kind"))

    def _state(self):
        return self._call("state.get")

    # connection
    def connect(self, port, baud=115200):
        self._call("machine.connect", {"port": port, "baud": baud})

    def disconnect(self):
        self._call("machine.disconnect")

    def set_option(self, name, value):
        if name == "auto_cooling":  # None or (on_s, off_s)
            self._call("settings.set", {"key": "machine.auto_cooling.enabled", "value": value is not None})
            if value is not None:
                self._call("settings.set", {"key": "machine.auto_cooling.on_s", "value": value[0]})
                self._call("settings.set", {"key": "machine.auto_cooling.off_s", "value": value[1]})
            return
        self._call("settings.set", {"key": self.OPTIONS[name], "value": value})

    # job
    def load_gcode(self, path):
        self._call("job.load", {"path": str(path)})

    def run_job(self, homing=False, passes=1):
        self._call("job.run", {"homing": homing, "passes": passes})

    def resume_job(self, position, homing=False, set_wco=False):
        self._call("job.resume", {"position": position, "homing": homing, "set_wco": set_wco})

    def abort_job(self):
        self._call("job.abort")

    # immediate / manual
    def send_command(self, line):
        self._call("machine.send", {"line": line})

    def custom_code(self, code):
        self._call("machine.custom_code", {"code": code})

    def feed_hold(self):
        self._call("machine.feed_hold")

    def resume(self):
        self._call("machine.resume")

    def safety_door(self):
        self._call("machine.safety_door")

    def soft_reset(self):
        self._call("machine.stop")

    def unlock(self):
        self._call("machine.unlock")

    def home(self):
        self._call("machine.home")

    def set_zero(self):
        self._call("machine.set_zero")

    def jog(self, direction, step, feed):
        self._call("machine.jog", {"direction": direction, "step_mm": float(step), "feed_mm_min": float(feed)})

    def jog_to(self, x, y, feed):
        self._call("machine.jog_to", {"x": float(x), "y": float(y), "feed_mm_min": float(feed)})

    def jog_abort(self):
        self._call("machine.jog_stop")

    def set_override_targets(self, feed, rapid, spindle):
        self._call("machine.overrides", {"feed": feed, "rapid": rapid, "power": spindle})

    def write_settings(self, settings):
        self._call("machine.write_settings", {"settings": {str(k): str(v) for k, v in settings.items()}})

    def refresh_settings(self):
        self._call("machine.read_settings")

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

    @property
    def firmware_vendor(self):
        v = self._state()["machine"]["version"]
        return None if v is None else v.get("vendor_info")

    @staticmethod
    def _point(p):
        return (float(p["x"]), float(p["y"]), float(p["z"]))

    @property
    def machine_position(self):
        return self._point(self._state()["machine"]["machine_position"])

    @property
    def work_offset(self):
        return self._point(self._state()["machine"]["work_offset"])

    @property
    def overrides(self):
        return tuple(int(v) for v in self._state()["machine"]["overrides"])

    @property
    def buffer_size(self):
        return int(self._state()["machine"]["buffer_size"])

    @property
    def detected_ip(self):
        return self._state()["machine"]["detected_ip"]

    @property
    def last_issue(self):
        return str(self._state()["machine"]["last_issue"])

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
