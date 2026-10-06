"""A fake Grbl 1.1 controller, independent from the transport it is attached to.

The device consumes raw bytes (``receive``) and produces raw bytes through
``output`` (a callable set by the link: in-process transport or a PTY pump).
It records everything it receives so tests can assert on the exact wire traffic.

Model (deliberately simple and deterministic):

* Real-time bytes (``?``, ``!``, ``~``, ``0x18``, ``0x84``, ``0x85``, ``0x90..0x9D``)
  are handled immediately and never enter the RX buffer, as in Grbl.
* Every other byte enters a serial RX buffer of ``rx_size`` bytes (Grbl 1.1:
  128, reported as ``Bf:..,128`` when empty and as ``[OPT:V,15,128]``). Hosts that
  learn nothing from the board must assume the classic 127.
  ``rx_used`` counts bytes received and not yet acknowledged; ``max_rx_used``
  keeps the high-water mark and ``overflows`` counts bytes that did not fit.
* A complete line is *executed* (removed from the RX buffer and answered with
  ``ok``/``error:N``) either immediately (``auto_ack=True``) or when the test
  calls ``release(n)``. While in feed hold no line is executed.
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

DEFAULT_SETTINGS: dict[int, str] = {
    0: "10", 1: "25", 2: "0", 3: "0", 4: "0", 5: "0", 6: "0", 10: "1", 11: "0.010", 12: "0.002",
    13: "0", 20: "0", 21: "0", 22: "0", 23: "0", 24: "25.000", 25: "500.000", 26: "250", 27: "1.000",
    30: "1000", 31: "0", 32: "1", 100: "80.000", 101: "80.000", 102: "250.000", 110: "6000.000",
    111: "6000.000", 112: "500.000", 120: "500.000", 121: "500.000", 122: "10.000", 130: "400.000",
    131: "300.000", 132: "200.000",
}

RT_STATUS = 0x3F  # ?
RT_HOLD = 0x21  # !
RT_RESUME = 0x7E  # ~
RT_RESET = 0x18  # ctrl-x
RT_DOOR = 0x84
RT_JOG_CANCEL = 0x85
# Grbl 1.1: '?', '!', '~', ctrl-x and every extended-ASCII byte (0x80-0xFF) are
# real-time commands; unknown ones are ignored. Anything else enters the line buffer.
REALTIME = {RT_STATUS, RT_HOLD, RT_RESUME, RT_RESET} | set(range(0x80, 0x100))


@dataclass
class Event:
    kind: str  # "rt" (real-time byte) | "line" (complete line, without the newline)
    value: int | str
    rx_used_after: int = 0


@dataclass
class FakeGrbl:
    version: str = "1.1f"
    welcome: str | None = None  # default: "Grbl {version} ['$' for help]"
    rx_size: int = 128
    auto_ack: bool = True
    settings: dict[int, str] = field(default_factory=lambda: dict(DEFAULT_SETTINGS))
    opt_line: str = "[OPT:V,15,128]"
    ver_line: str | None = None
    report_buffer: bool = True
    report_overrides: bool = True
    error_rules: list[tuple[str, int]] = field(default_factory=list)  # (regex, code)
    send_welcome_on_open: bool = True
    ok_first: bool = False  # answer "ok" before the $$ / $I data lines (seen on some clones)
    data_delay: float = 0.0  # with ok_first: seconds between the "ok" and the data lines
    data_gap: float = 0.03  # with data_delay: seconds between consecutive data lines

    def __post_init__(self) -> None:
        self.output = lambda data: None
        self.cv = threading.Condition()
        self.events: list[Event] = []
        self.raw = bytearray()
        self.lines: list[str] = []  # complete lines received, in order
        self.realtime: list[int] = []
        self.responses: list[str] = []
        self._partial = bytearray()
        self._rxq: deque[bytes] = deque()  # complete lines waiting for execution (with \n)
        self.rx_used = 0
        self.max_rx_used = 0
        self.overflows = 0
        self.state = "Idle"
        self.hold = False
        self.check_mode = False
        self.alarm: int | None = None
        self.mpos = [0.0, 0.0, 0.0]
        self.wco = [0.0, 0.0, 0.0]
        self.absolute = True
        self.feed = 0.0
        self.spindle = 0.0
        self.ov = [100, 100, 100]  # feed, rapids, spindle
        self.resets = 0

    # ------------------------------------------------------------------ wiring
    def connected(self) -> None:
        """Called by the link when the host opens the port."""
        if self.send_welcome_on_open:
            self._emit(self.welcome_line)

    @property
    def welcome_line(self) -> str:
        return self.welcome if self.welcome is not None else f"Grbl {self.version} ['$' for help]"

    def _emit(self, text: str) -> None:
        self.responses.append(text)
        self.output((text + "\r\n").encode())

    # ------------------------------------------------------------------ input
    def receive(self, data: bytes) -> None:
        with self.cv:
            for b in data:
                self.raw.append(b)
                if b in REALTIME:
                    self._realtime(b)
                    continue
                if self.rx_used >= self.rx_size:
                    self.overflows += 1  # Grbl would silently drop it
                self.rx_used += 1
                self.max_rx_used = max(self.max_rx_used, self.rx_used)
                self._partial.append(b)
                if b == 0x0A:
                    line = bytes(self._partial)
                    self._partial.clear()
                    text = line.decode(errors="replace").rstrip("\r\n")
                    self.lines.append(text)
                    self.events.append(Event("line", text, self.rx_used))
                    self._rxq.append(line)
            self._pump()
            self.cv.notify_all()

    def _pump(self) -> None:
        while self.auto_ack and self._rxq and not self.hold:
            self._execute_next()

    def release(self, n: int = 1) -> int:
        """Execute up to ``n`` buffered lines (manual-ack mode). Returns how many ran."""
        done = 0
        with self.cv:
            while done < n and self._rxq and not self.hold:
                self._execute_next()
                done += 1
            self.cv.notify_all()
        return done

    def set_auto_ack(self, value: bool) -> None:
        with self.cv:
            self.auto_ack = value
            self._pump()
            self.cv.notify_all()

    @property
    def pending_lines(self) -> int:
        return len(self._rxq)

    def wait_for(self, predicate, timeout: float = 5.0) -> bool:
        with self.cv:
            ok = self.cv.wait_for(lambda: predicate(self), timeout)
        if not ok:
            raise TimeoutError(f"device condition not met in {timeout}s (lines={self.lines[-5:]}, rt={self.realtime[-5:]})")
        return ok

    def push(self, line: str) -> None:
        """Send an unsolicited line to the host (e.g. ALARM:1, [MSG:...])."""
        with self.cv:
            self._emit(line)

    # ------------------------------------------------------------------ real-time
    def _realtime(self, b: int) -> None:
        self.realtime.append(b)
        self.events.append(Event("rt", b, self.rx_used))
        if b == RT_STATUS:
            self._emit(self.status_report())
        elif b == RT_HOLD:
            if self.state in ("Run", "Idle", "Jog"):
                self.hold = True
                self.state = "Hold"
        elif b == RT_RESUME:
            if self.hold:
                self.hold = False
                self.state = "Run" if self._rxq else "Idle"
                self._pump()
        elif b == RT_RESET:
            self._reset()
        elif b == RT_DOOR:
            self.hold = True
            self.state = "Door"
        elif b == RT_JOG_CANCEL:
            if self.state == "Jog":
                self.state = "Idle"
        elif 0x90 <= b <= 0x9D:
            self._override(b)

    def _override(self, b: int) -> None:
        f, r, s = self.ov
        if b == 0x90:
            f = 100
        elif b == 0x91:
            f += 10
        elif b == 0x92:
            f -= 10
        elif b == 0x93:
            f += 1
        elif b == 0x94:
            f -= 1
        elif b == 0x95:
            r = 100
        elif b == 0x96:
            r = 50
        elif b == 0x97:
            r = 25
        elif b == 0x99:
            s = 100
        elif b == 0x9A:
            s += 10
        elif b == 0x9B:
            s -= 10
        elif b == 0x9C:
            s += 1
        elif b == 0x9D:
            s -= 1
        self.ov = [max(10, min(200, f)), r, max(10, min(200, s))]

    def _reset(self) -> None:
        self.resets += 1
        self._rxq.clear()
        self._partial.clear()
        self.rx_used = 0
        self.hold = False
        self.check_mode = False
        self.ov = [100, 100, 100]
        self.state = "Alarm" if self.alarm is not None else "Idle"
        self._emit("")
        self._emit(self.welcome_line)

    def status_report(self) -> str:
        st = self.state
        if st == "Idle" and self._rxq:
            st = "Run"  # lines buffered but not executed yet (manual-ack mode)
        if st == "Hold":
            st = "Hold:0"
        parts = [st, "MPos:" + ",".join(f"{v:.3f}" for v in self.mpos)]
        if self.report_buffer:
            free = self.rx_size - self.rx_used
            parts.append(f"Bf:{max(0, 15 - len(self._rxq))},{free}")
        parts.append(f"FS:{self.feed:g},{self.spindle:g}")
        if any(self.wco):
            parts.append("WCO:" + ",".join(f"{v:.3f}" for v in self.wco))
        if self.report_overrides:
            parts.append("Ov:" + ",".join(str(v) for v in self.ov))
        return "<" + "|".join(parts) + ">"

    # ------------------------------------------------------------------ execution
    def _execute_next(self) -> None:
        line = self._rxq.popleft()
        self.rx_used -= len(line)
        text = line.decode(errors="replace").strip()
        replies = self._execute(text)
        if self.ok_first and self.data_delay and text.upper() in ("$$", "$I") and replies[0] == "ok":
            self._emit("ok")
            late = replies[1:]

            def send_late():
                for i, reply in enumerate(late):
                    if i:
                        time.sleep(self.data_gap)
                    with self.cv:
                        self._emit(reply)

            # PTY-only (pure Python thread): emulates a slow board
            t = threading.Timer(self.data_delay, send_late)
            t.daemon = True
            t.start()
            return
        for reply in replies:
            self._emit(reply)

    def _execute(self, text: str) -> list[str]:
        for rx, code in self.error_rules:
            if re.search(rx, text):
                return [f"error:{code}"]
        if text == "":
            return ["ok"]
        up = text.upper()
        if up == "$$":
            data = [f"${k}={v}" for k, v in sorted(self.settings.items())]
            return ["ok"] + data if self.ok_first else data + ["ok"]
        if up == "$I":
            data = [self.ver_line or f"[VER:{self.version}.20170801:]", self.opt_line]
            return ["ok"] + data if self.ok_first else data + ["ok"]
        if up == "$X":
            self.alarm = None
            self.state = "Idle"
            return ["[MSG:Caution: Unlocked]", "ok"]
        if up == "$H":
            self.alarm = None
            self.mpos = [0.0, 0.0, 0.0]
            self.state = "Idle"
            return ["ok"]
        if up == "$C":
            self.check_mode = not self.check_mode
            self.state = "Check" if self.check_mode else "Idle"
            return ["[MSG:Enabled]" if self.check_mode else "[MSG:Disabled]", "ok"]
        if up == "$G":
            return ["[GC:G0 G54 G17 G21 G90 G94 M5 M9 T0 F0 S0]", "ok"]
        m = re.match(r"^\$(\d+)=(.*)$", text)
        if m:
            key = int(m.group(1))
            if key not in self.settings:
                return ["error:3"]
            self.settings[key] = m.group(2).strip()
            return ["ok"]
        if up.startswith("$J="):
            if self.alarm is not None:
                return ["error:8"]
            self._move(up[3:])
            return ["ok"]
        if up.startswith("$"):
            return ["error:3"]
        if self.alarm is not None:
            return ["error:9"]
        if not self.check_mode:
            self._move(up)
        return ["ok"]

    def _move(self, gcode: str) -> None:
        words = dict(re.findall(r"([A-Z])([-+]?[0-9]*\.?[0-9]+)", gcode))
        g = words.get("G")
        if g == "90":
            self.absolute = True
        elif g == "91":
            self.absolute = False
        absolute = self.absolute
        if "G90" in gcode:
            absolute = True
        if "G91" in gcode:
            absolute = False
        for i, ax in enumerate("XYZ"):
            if ax in words:
                v = float(words[ax])
                self.mpos[i] = v if absolute else self.mpos[i] + v
        if "F" in words:
            self.feed = float(words["F"])
        if "S" in words:
            self.spindle = float(words["S"])

    # ------------------------------------------------------------------ helpers for tests
    def alarm_now(self, code: int) -> None:
        with self.cv:
            self.alarm = code
            self.state = "Alarm"
            self._rxq.clear()
            self.rx_used = 0
            self._emit(f"ALARM:{code}")
            self.cv.notify_all()

    def stream_lines(self) -> list[str]:
        """Lines received that are not system ($) commands."""
        return [ln for ln in self.lines if not ln.startswith("$")]
