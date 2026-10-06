"""Ways to attach a FakeGrbl to a host.

Threading rule (pythonnet on Mono 6.8, see README "Known issues"): only the main
Python thread may call into the CLR, and CLR threads must never run Python code.

* ``LoopbackLink`` uses the C# ``LaserGRBLTests.LoopbackCom`` (tools/TestSupport.cs)
  as the core's ``IComWrapper``. The device is pumped *from the main thread*
  (``pump()``), which the rig does inside every wait loop. Used by white-box tests.
* ``PtyLink`` exposes the device behind a pseudo terminal (``/dev/pts/N``). Its pump
  thread only does ``os.read``/``os.write`` plus pure-Python device logic, so it never
  touches the CLR. Any host can open the path: the C# core through Mono's
  ``SerialPort`` (``UsbSerial`` wrapper) or a future Rust binary. Used by the
  protocol (black-box) tests.
"""

from __future__ import annotations

import os
import select
import threading
import tty
import weakref

from .fake_grbl import FakeGrbl


class LoopbackLink:
    def __init__(self, device: FakeGrbl):
        from LaserGRBLTests import LoopbackCom

        self.device = device
        self.com = LoopbackCom()
        device.output = self._to_host

    def _to_host(self, data: bytes) -> None:
        self.com.FeedHost(data.decode(errors="replace"))

    def pump(self, timeout_ms: int = 0) -> bool:
        """Move pending traffic between host and device. Main thread only."""
        moved = False
        for _ in range(self.com.TakeConnectEvents()):
            self.device.connected()
            moved = True
        data = self.com.TakeTx(timeout_ms)
        if data is not None and len(data):
            self.device.receive(bytes(bytearray(data)))
            moved = True
        return moved


OPEN_PTYS: "weakref.WeakSet[PtyLink]" = weakref.WeakSet()


def hang_up_all() -> None:
    """Close every open PtyLink (call before closing hosts, see PtyLink.close)."""
    for link in list(OPEN_PTYS):
        link.close()


class PtyLink:
    """Runs ``device`` behind a PTY. ``path`` is the slave device name to open."""

    def __init__(self, device: FakeGrbl):
        OPEN_PTYS.add(self)
        self.device = device
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        self.path = os.ttyname(self.slave)
        self._stop = threading.Event()
        self._wlock = threading.Lock()
        device.output = self._write
        self._thread = threading.Thread(target=self._pump, name=f"pty-{self.path}", daemon=True)
        self._thread.start()

    def _write(self, data: bytes) -> None:
        with self._wlock:
            if self._stop.is_set():
                return  # closed: late writes (e.g. delayed replies) are dropped
            view = memoryview(data)
            while view:
                n = os.write(self.master, view)
                view = view[n:]

    def _pump(self) -> None:
        while not self._stop.is_set():
            r, _, _ = select.select([self.master], [], [], 0.02)
            if not r:
                continue
            try:
                data = os.read(self.master, 4096)
            except OSError:
                return
            if data:
                self.device.receive(data)

    def announce(self) -> None:
        """Simulate the board boot banner (the host opened the port)."""
        self.device.connected()

    def close(self) -> None:
        """Hang up the line. Close this *before* closing the host: the host's reader
        blocked in poll() on the slave side only wakes up on the hang-up."""
        if self._stop.is_set():
            return
        with self._wlock:
            self._stop.set()
        self._thread.join(timeout=2)
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass
