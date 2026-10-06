"""Instantiating the C# ``GrblCore`` (and its firmware variants) outside the WinForms app.

How the core is isolated (also in README.md, "White-box path"):

* ``syncro``: the core marshals its events through a ``System.Windows.Forms.Control``.
  A real Control needs an X display under Mono, so we pass an *uninitialized*
  Control (``FormatterServices.GetUninitializedObject``). Its ``InvokeRequired`` is
  false (no creator thread), so events are raised synchronously on the raising
  thread, where the C# ``EventRecorder`` stores them.
* ``PreviewForm``/``JogForm``: only stored by ``HotKeysManager.Init``; ``None`` is fine.
* transport: the protected ``com`` field is replaced with the C# ``LoopbackCom`` bound
  to a ``FakeGrbl`` (``LoopbackLink``), or the core is configured with ``UsbSerial``
  pointing at a PTY (protocol tests).
* ``Settings`` is a static dictionary persisted under the throw-away HOME set by
  ``runtime.load``; ``reset_settings()`` clears it between tests.

Two ways to drive a core:

* *stepped* (deterministic, single thread): the TX/RX threads are never started;
  ``step_tx()`` runs one TX-loop iteration, ``rx(line)`` hands a line to the parser,
  ``pump()`` runs send/answer/parse until quiescent.
* *live*: ``connect()`` runs ``OpenCom`` and the real threads; ``wait(pred)`` polls
  ``pred`` while pumping the device from the main thread.
"""

from __future__ import annotations

import time

import System
from System.Runtime.Serialization import FormatterServices

from . import clr_util as cu
from .fake_grbl import FakeGrbl
from .links import LoopbackLink, PtyLink

import LaserGRBL
from LaserGRBL import GrblCore, Settings
from LaserGRBLTests import EventRecorder, Helpers

MacStatus = GrblCore.MacStatus


def fake_syncro():
    import System.Windows.Forms as WF

    return FormatterServices.GetUninitializedObject(cu.clr_type(WF.Control))


def settings_dict():
    return cu.sget(Settings, "dic")


def reset_settings(**values) -> None:
    settings_dict().Clear()
    cu.sset(Settings, "LastCause", None)
    for k, v in values.items():
        Settings.SetObject(k, v)


def set_setting(key: str, value) -> None:
    Settings.SetObject(key, value)


def get_setting(key: str, default=None):
    """Raw value stored in Settings (``default`` if missing)."""
    d = settings_dict()
    return d[key] if d.ContainsKey(key) else default


class CoreRig:
    """``link="loopback"``: in-memory C# transport, device pumped by the main thread.
    ``link="pty"``: the core's own UsbSerial wrapper on a PTY, device on a Python
    thread. Needed when the test calls a core API that blocks the calling thread
    while waiting for the device (WriteConfig, RefreshConfig, ...)."""

    def __init__(self, core_cls=GrblCore, device: FakeGrbl | None = None, link: str = "loopback", events: bool = True):
        self.device = device or FakeGrbl()
        self.core = core_cls(fake_syncro(), None, None)
        if link == "pty":
            from LaserGRBL.ComWrapper import WrapperType

            self.link = PtyLink(self.device)
            self.com = None
            self.core.Configure(WrapperType.UsbSerial, self.link.path, System.Int32(115200))
        else:
            self.link = LoopbackLink(self.device)
            self.com = self.link.com
            cu.set(self.core, "com", self.com)
        self.recorder = EventRecorder(self.core) if events else None

    @property
    def events(self) -> list[str]:
        return [str(e) for e in self.recorder.Snapshot()] if self.recorder else []

    # ------------------------------------------------------------------ stepped
    def set_status(self, status) -> None:
        cu.call(self.core, "SetStatus", status)

    def open_stepped(self, status=MacStatus.Idle) -> None:
        """Mark the transport open and the machine in ``status`` without threads."""
        self.com.ForceOpen(True)
        self.set_status(status)

    def rx(self, line: str) -> None:
        cu.call(self.core, "ManageReceivedLine", line)

    def step_tx(self, n: int = 1) -> None:
        for _ in range(n):
            cu.call(self.core, "ThreadTX")

    def send_line(self) -> None:
        cu.call(self.core, "SendLine")

    def can_send(self) -> bool:
        return bool(cu.call(self.core, "CanSend"))

    def deliver(self) -> int:
        """Device processes what the host wrote; host parses every reply. Returns #lines parsed."""
        self.link.pump()
        n = 0
        while True:
            line = self.com.TakeHostLine()
            if line is None:
                return n
            line = line.strip()
            if line:
                self.rx(line)
                n += 1

    def ack(self, n: int = 1) -> int:
        """Manual-ack device: deliver host bytes, execute ``n`` lines, parse the replies."""
        self.link.pump()
        done = self.device.release(n)
        self.deliver()
        return done

    def pump(self, max_steps: int = 100000) -> int:
        """Stepped full-duplex loop: send what fits, let the device answer, parse replies."""
        steps = 0
        while steps < max_steps:
            sent = False
            while self.can_send():
                self.send_line()
                sent = True
            parsed = self.deliver()
            if not sent and not parsed:
                break
            steps += 1
        return steps

    @property
    def queue(self):
        return cu.get(self.core, "mQueuePtr")

    @property
    def pending(self):
        return cu.get(self.core, "mPending")

    @property
    def sent(self):
        return cu.get(self.core, "mSentPtr")

    @property
    def tp(self):
        return cu.get(self.core, "mTP")

    def sent_rows(self) -> list:
        """mSentPtr rows as their concrete types (GrblCommand / GrblMessage)."""
        return [r.__implementation__ for r in self.sent]

    def sent_texts(self) -> list[str]:
        if System.Object.ReferenceEquals(self.sent, cu.get(self.core, "mSent")):
            return [str(t) for t in Helpers.SentTexts(self.core)]  # locked snapshot
        return [str(r.GetDecodedMessage()) for r in self.sent]

    def queue_texts(self) -> list[str]:
        return [str(c.Command) for c in self.queue]

    # ------------------------------------------------------------------ live
    def wait(self, predicate, timeout: float = 10.0, message: str = "") -> None:
        """Poll ``predicate`` while pumping the device (main thread)."""
        deadline = time.monotonic() + timeout
        while True:
            self._pump_once()
            if predicate():
                return
            if time.monotonic() >= deadline:
                raise TimeoutError(message or f"condition not met within {timeout}s; device lines={self.device.lines[-8:]}")

    def run_for(self, seconds: float) -> None:
        """Keep the device pumped for a while (used to assert something does NOT happen)."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self._pump_once()

    def _pump_once(self) -> None:
        if isinstance(self.link, LoopbackLink):
            self.link.pump(timeout_ms=2)
        else:
            time.sleep(0.002)  # the PTY link pumps itself

    def connect(self, wait_config: bool = True, timeout: float = 10.0) -> None:
        self.core.OpenCom()
        self.wait(lambda: self.core.IsConnected, timeout, "core did not reach a connected state")
        if wait_config:
            self.wait_config_refresh(timeout)

    def wait_config_refresh(self, timeout: float = 10.0) -> None:
        """Connecting->Idle triggers $$ (and $I) on a pool thread after 500 ms; wait for it."""
        want_i = bool(get_setting("Query MachineInfo ($I) at connect", True))
        self.wait(lambda: "$$" in self.device.lines and (not want_i or "$I" in self.device.lines), timeout,
                  "config refresh not requested")
        self.wait(self.config_idle, timeout, "config refresh did not finish")
        self.wait(lambda: self.core.MachineStatus == MacStatus.Idle, timeout, "machine not idle after refresh")

    def config_idle(self) -> bool:
        core = self.core
        return (System.Object.ReferenceEquals(cu.get(core, "mQueuePtr"), cu.get(core, "mQueue"))
                and System.Object.ReferenceEquals(cu.get(core, "mSentPtr"), cu.get(core, "mSent"))
                and cu.get(core, "mPending").Count == 0)

    def close(self) -> None:
        if isinstance(self.link, PtyLink):
            self.link.close()  # first: wakes the RX thread blocked on the serial port
        try:
            self.core.CloseCom(True)
        except Exception:
            pass
        for name in ("TX", "RX"):
            try:
                cu.get(self.core, name).Stop()
            except Exception:
                pass


def wait_loaded(gfile, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while cu.get(gfile, "mLoadingThread") is not None:
        if time.monotonic() >= deadline:
            raise TimeoutError("GrblFile background load did not finish")
        time.sleep(0.002)


def load_file_sync(gfile, path: str, append: bool = False, timeout: float = 10.0) -> None:
    """``GrblFile.LoadFile`` parses on a background CLR thread; wait for it to finish."""
    gfile.LoadFile(path, append)
    wait_loaded(gfile, timeout)


def new_grblfile():
    return LaserGRBL.GrblFile()
