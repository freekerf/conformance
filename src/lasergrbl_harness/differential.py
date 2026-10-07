"""Differential testing: the C# host and FreeKerf on the same inputs.

* G-code analysis: ``golden.analyze_csharp`` and ``golden.analyze_rust`` on the same
  file, compared field by field (the golden rounding rules apply to both).
* Protocol: a scenario (device behaviour + host options + a list of operations)
  is played against each host on its own fake Grbl; what the device received for
  each operation (lines in order, real-time bytes except the '?' polls, peak RX
  buffer use) and the coarse host state afterwards are compared.

Only differences documented in FreeKerf's ``doc/divergences.md`` may be removed,
by the rules in :data:`RULES` (DIV id -> normalization applied to *both* traces).
Never add a rule without its entry there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from hypothesis import strategies as st

# ====================================================================== G-code programs

G_VALUES = ["0", "1", "2", "3", "4", "90", "91", "20", "21", "92", "17", "18", "19", "28", "38.2",
            "80", "93", "94", "53", "54", "55", "91.1", "40", "43.1", "1.0", "00", "01", "2.5"]
M_VALUES = ["3", "4", "5", "8", "9", "30", "2", "05", "3.0"]
SPECIAL_NUMBERS = [".5", "5.", "-.5", "+1", "007", "-0", "0.000", "1-", "1..5", "-4-2", "", "-", "1e3",
                   "99999999999999999999999999999", "79228162514264337593543950336",
                   "0.0000000000000000000000000001", "0.00000000000000000000000000001",
                   "12345678901234567890.123456789", "١٢", "²", "1.5.5"]
SPECIAL_LINES = ["", "   ", "\t", "(only a comment)", ";only a comment", "$H", "$X", "$J=G91X1F100",
                 "$110=500", "%", "N10 G1 X1", "G1 X1 (a;b) Y2", "((nested) X3) Y4", "G1 X1 Y", "M3 S",
                 "g1x3y3f500", "G0 X1 ; tail (x)", "G1 X5 F600 S1000 M3", "G90 G1 X3", "Xé1 Y2",
                 "G1 Xß1", "Gı1 X1", "G1 X1\tY2", "T1 M6", "G28 X0 Y0", "G4 P0.25", "G4 S1"]
SEPARATORS = ["", " ", " ", "  ", "\t"]


def _number(draw):
    kind = draw(st.integers(0, 9))
    if kind <= 3:
        return str(draw(st.integers(-300, 300)))
    if kind <= 7:
        whole = draw(st.integers(-300, 300))
        frac = draw(st.text("0123456789", min_size=1, max_size=4))
        sign = "-" if whole == 0 and draw(st.booleans()) else ""
        return f"{sign}{whole}.{frac}"
    return draw(st.sampled_from(SPECIAL_NUMBERS))


@st.composite
def gcode_word(draw):
    letter = draw(st.sampled_from("GGGMXXXYYYZIJRFFSSP" + "ABCDEHKLNOQTUVW"))
    if letter == "G" and draw(st.integers(0, 4)):
        value = draw(st.sampled_from(G_VALUES))
    elif letter == "M" and draw(st.integers(0, 4)):
        value = draw(st.sampled_from(M_VALUES))
    else:
        value = _number(draw)
    return letter + value


@st.composite
def gcode_line(draw):
    if draw(st.integers(0, 6)) == 0:
        return draw(st.sampled_from(SPECIAL_LINES))
    words = draw(st.lists(gcode_word(), min_size=1, max_size=5))
    seps = [draw(st.sampled_from(SEPARATORS)) for _ in words]
    line = draw(st.sampled_from(["", "", "", " ", "  "]))
    for w, s in zip(words, seps):
        line += w + s
    comment = draw(st.integers(0, 8))
    if comment == 0:
        line += "(c " + draw(st.sampled_from(["x", "X9", "a b", ""])) + ")"
    elif comment == 1:
        line += ";" + draw(st.sampled_from(["", " note", "X9 Y9"]))
    elif comment == 2:
        i = draw(st.integers(0, len(line)))
        line = line[:i] + " (in) " + line[i:]
    if draw(st.integers(0, 4)) == 0:
        line = line.lower()
    return line


@st.composite
def arc_program(draw):
    """Geometrically plausible jobs: moves and arcs with I/J or R, laser on and off."""
    coord = st.integers(-2000, 2000).map(lambda v: f"{v / 20:g}")
    lines = [draw(st.sampled_from(["G90", "G91", "G21"]))]
    for _ in range(draw(st.integers(1, 12))):
        kind = draw(st.integers(0, 5))
        if kind == 0:
            lines.append(f"G0 X{draw(coord)} Y{draw(coord)}")
        elif kind == 1:
            lines.append(f"G1 X{draw(coord)} Y{draw(coord)} F{draw(st.sampled_from([1, 60, 600, 1200, 6000, 60000]))}")
        elif kind == 2:
            lines.append(draw(st.sampled_from(["M3 S500", "M4 S1000", "M5", "M3 S0", "S250"])))
        else:
            g = draw(st.sampled_from(["G2", "G3"]))
            if draw(st.booleans()):
                lines.append(f"{g} X{draw(coord)} Y{draw(coord)} I{draw(coord)} J{draw(coord)}")
            else:
                lines.append(f"{g} X{draw(coord)} Y{draw(coord)} R{draw(coord)}")
    return lines


@st.composite
def gcode_program(draw):
    if draw(st.integers(0, 3)) == 0:
        lines = draw(arc_program())
    else:
        lines = draw(st.lists(gcode_line(), min_size=1, max_size=20))
    newline = draw(st.sampled_from(["\n", "\n", "\r\n"]))
    text = newline.join(lines)
    if draw(st.booleans()):
        text += newline
    return text


# ====================================================================== comparison

def casing_differs(text: str) -> bool:
    """DIV-052: LaserGRBL uppercases G-code with the current culture (the harness runs
    the invariant one), FreeKerf with the Unicode default mapping. True when the two
    give a different text (non-ASCII letters such as 'ı' or 'ß')."""
    import System

    return str(System.String(text).ToUpper()) != text.upper()


def csharp_analysis_aborts(text: str) -> bool:
    """DIV-053: ``GrblFile.Analyze`` rethrows the first exception of a command (e.g. a
    time or range overflow of an absurd move): LaserGRBL stops analyzing there,
    FreeKerf goes on. True when LaserGRBL's analysis loop throws on this program
    (the loop of ``GrblFile.Analyze``, with the golden configuration)."""
    import System
    from LaserGRBL import GrblCommand, GrblConfST, GrblCore, ProgramRange

    from .golden import CONFIG

    table = System.Collections.Generic.Dictionary[int, str]()
    for k, v in CONFIG.items():
        table[k] = v
    conf = GrblConfST(GrblCore.GrblVersionInfo(1, 1, "f"), table)
    spb = GrblCommand.StatePositionBuilder()
    rng = ProgramRange()
    for line in text.splitlines():
        if not line.strip():
            continue  # GrblFile.LoadFile skips blank lines
        cmd = GrblCommand(line)
        try:
            spb.AnalyzeCommand(cmd, True, conf)
            rng.UpdateSRange(spb.S)
            arc = spb.LastArcHelperResult
            if arc is not None:
                rng.UpdateXYRange(arc.BBox.X, arc.BBox.Y, arc.BBox.Width, arc.BBox.Height, spb.LaserBurning)
            else:
                rng.UpdateXYRange(spb.X, spb.Y, spb.LaserBurning)
        except Exception:
            return True
    return False


# input filters of the G-code comparison: DIV id -> predicate (True = the program
# is outside what can be compared, because of that divergence)
GCODE_RULES = {
    "DIV-052": casing_differs,
    "DIV-053": csharp_analysis_aborts,
}


def gcode_comparable(text: str) -> bool:
    return not any(rule(text) for rule in GCODE_RULES.values())


ANALYSIS_FIELDS = ["input", "commands", "wire", "stream", "offsets_s", "estimated_time_s", "drawing_range",
                   "moving_range", "spindle_range", "quadrant"]


def first_difference(cs: dict, rs: dict, fields=ANALYSIS_FIELDS):
    """``None`` when equal, else ``(field, index or None, C# value, Rust value)``."""
    for f in fields:
        a, b = cs.get(f), rs.get(f)
        if a == b:
            continue
        if isinstance(a, list) and isinstance(b, list):
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    return f, i, x, y
            return f, min(len(a), len(b)), a[len(b):], b[len(a):]
        return f, None, a, b
    extra = set(cs) ^ set(rs)
    if extra:
        return "keys", None, sorted(set(cs) - set(rs)), sorted(set(rs) - set(cs))
    return None


# ====================================================================== protocol scenarios

@dataclass
class Scenario:
    device: dict = field(default_factory=dict)  # FakeGrbl keyword arguments
    options: dict = field(default_factory=dict)  # HostAdapter.set_option before connecting
    ops: list = field(default_factory=list)  # (name, *args)


JOB_LINES = ["G1 X{i} Y{j} F{f}", "G0 X{i} Y{j}", "M3 S{s}", "G1 X{j} F{f}", "M5", "G2 X{i} Y0 I5 J0 F{f}",
             "(comment {i})", "G4 P0", "S{s}"]
SEND_LINES = ["G0 X5", "G1 X1 F100", "M3 S100", "M5", "$X", "$110=500", "g0 x2 y3", "G4 P0", "G92 X0",
              "$$", "$G", "G1 X1 (c) Y2"]
CUSTOM_CODES = ["M3 S[$30/2]\nM5", "~\n0x9e\nG0 X[left]", "G0 X[MPos.X+1] Y[WCO.Y]", "?\nG0 X[$130/4]",
                "G0 X[nope+]", "0xZZ\n$X", "G1 X[jogstep] F[jogspeed]", "!\n~"]


@st.composite
def job_spec(draw):
    n = draw(st.integers(1, 25))
    rows = []
    for k in range(n):
        tpl = draw(st.sampled_from(JOB_LINES))
        rows.append(tpl.format(i=k % 37, j=(k * 7) % 23, f=draw(st.sampled_from([100, 600, 1000, 3000])),
                               s=draw(st.sampled_from([0, 100, 1000]))))
    return rows


@st.composite
def protocol_op(draw):
    kind = draw(st.sampled_from(["send", "send", "jog", "jog_to", "overrides", "job", "job", "job_error",
                                 "job_hold", "job_reset", "job_abort", "job_alarm", "job_fill", "custom",
                                 "write_settings", "set_zero", "home", "unlock", "job_resume", "safety_door"]))
    if kind == "send":
        return ("send", draw(st.sampled_from(SEND_LINES)))
    if kind == "jog":
        return ("jog", draw(st.sampled_from(["N", "S", "E", "W", "NE", "NW", "SE", "SW", "Zup", "Zdown", "Home"])),
                draw(st.sampled_from([0.1, 1, 2.5, 10, 0.25, 0.04, 0.05])), draw(st.sampled_from([100, 1000, 1234.5])))
    if kind == "jog_to":
        return ("jog_to", draw(st.integers(-50, 500)) / 4, draw(st.integers(-50, 400)) / 4,
                draw(st.sampled_from([300, 1000])))
    if kind == "overrides":
        return ("overrides", draw(st.sampled_from([10, 50, 95, 100, 101, 130, 200])),
                draw(st.sampled_from([25, 50, 100])), draw(st.sampled_from([10, 90, 100, 107, 200])))
    if kind == "custom":
        return ("custom", draw(st.sampled_from(CUSTOM_CODES)))
    if kind == "write_settings":
        return ("write_settings", {draw(st.sampled_from([110, 111, 130, 131, 22, 999])): draw(st.sampled_from(["1", "500", "300.5"]))})
    if kind in ("set_zero", "home", "unlock", "safety_door"):
        return (kind,)
    if kind == "job_resume":
        return ("job_resume", draw(job_spec()), draw(st.integers(0, 45)))
    passes = draw(st.integers(1, 2)) if kind == "job" else 1
    return (kind, draw(job_spec()), passes)


@st.composite
def protocol_scenario(draw):
    rx = draw(st.sampled_from([128, 127, 256]))
    device = {
        "report_buffer": draw(st.booleans()),
        "rx_size": rx,
        "opt_line": f"[OPT:V,15,{rx}]",
        "ok_first": draw(st.integers(0, 5)) == 0,
    }
    if draw(st.integers(0, 3)) == 0:
        device["error_rules"] = [(draw(st.sampled_from([r"^G1X1Y", r"^M3", r"^G0X5$", r"F3000$"])),
                                  draw(st.sampled_from([2, 20, 33])))]
    options = {"streaming_mode": draw(st.sampled_from(["Buffered", "Buffered", "Synchronous", "RepeatOnError"])),
               "continuous_jog": draw(st.integers(0, 3)) == 0}
    ops = draw(st.lists(protocol_op(), min_size=1, max_size=4))
    return Scenario(device, options, ops)


# ---------------------------------------------------------------------- divergence rules
# DIV id -> function(trace: dict, host: "csharp" | "rust") -> trace. Applied to both sides.

_JOG_NUM = re.compile(r"([XYZ])(-?)(\d+(?:\.\d+)?)")


def _round_half_away(text: str) -> str:
    from decimal import ROUND_HALF_UP, Decimal

    return str(Decimal(text).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _div022(trace, host):
    # Jog steps: LaserGRBL formats them with "0.0" (0.25 -> 0.3), FreeKerf with up to
    # three decimals. Compare relative jogs at LaserGRBL's precision.
    def fix(line):
        if not line.startswith("$J=G91"):
            return line
        return _JOG_NUM.sub(lambda m: m.group(1) + m.group(2) + _round_half_away(m.group(3)), line)

    trace["lines"] = [fix(x) for x in trace["lines"]]
    return trace


def _div019(trace, host):
    # Resume: LaserGRBL queues an empty "settled modal groups" command when none is set.
    out = []
    for i, line in enumerate(trace["lines"]):
        if line == "" and i > 0 and trace["lines"][i - 1].startswith("M5G0") and trace["op"][0] == "job_resume":
            continue
        out.append(line)
    trace["lines"] = out
    return trace


def _div020(trace, host):
    # Safety door: LaserGRBL sends '@' (it prefixes the next line), FreeKerf 0x84; the
    # board then holds in Door only with FreeKerf, so only FreeKerf's cycle start (~)
    # that follows has an effect.
    if trace["op"][0] != "safety_door":
        return trace
    trace["lines"] = [x[1:] if x.startswith("@") else x for x in trace["lines"]]
    trace["realtime"] = [b for b in trace["realtime"] if b not in (0x84, 0x7E)]
    return trace


def _div024(trace, host):
    # Settings write outside Idle/Alarm: LaserGRBL skips it silently, FreeKerf refuses.
    if trace["op"][0] == "write_settings" and trace.get("error", "").startswith("refused:"):
        trace["error"] = ""
    return trace


RULES = {
    "DIV-019": _div019,
    "DIV-020": _div020,
    "DIV-022": _div022,
    "DIV-024": _div024,
}


def normalize(trace: dict, host: str) -> dict:
    for rule in RULES.values():
        trace = rule(trace, host)
    return trace


# ---------------------------------------------------------------------- playing a scenario

def _error_kind(exc) -> str:
    kind = getattr(exc, "kind", None)
    if kind:
        return f"{kind}:"
    name = type(exc).__name__
    if "WriteConfigException" in name or "WriteConfig" in str(exc):
        return "failed:"
    return f"exception:{name}"


def _quiet(host, device, timeout=15.0):
    """Wait until the job is over, the device has nothing buffered and the wire has
    been silent (no new line) for 0.3 s."""
    from .host import wait
    from .waiting import stays_true

    wait(lambda: not host.job_running and device.pending_lines == 0, timeout, "scenario did not settle")
    wait(lambda: stays_true(lambda n=len(device.lines): len(device.lines) == n and device.pending_lines == 0, 0.3),
         timeout, "wire did not go quiet")
    polls = device.realtime.count(0x3F)  # then two more status reports: coarse states are current
    wait(lambda: device.realtime.count(0x3F) >= polls + 2, timeout, "status polling stopped")


def _job_file(tmp_dir, lines, name):
    from pathlib import Path

    p = Path(tmp_dir) / name
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def _run_op(host, device, op, tmp_dir, k, fill):
    from .host import wait
    from .jobs import FOOTER
    from .waiting import stays_true

    name = op[0]
    if name == "send":
        host.send_command(op[1])
    elif name == "jog":
        host.jog(op[1], op[2], op[3])
    elif name == "jog_to":
        host.jog_to(op[1], op[2], op[3])
    elif name == "overrides":
        host.set_override_targets(op[1], op[2], op[3])
        wait(lambda: device.ov == [op[1], op[2], op[3]], 10, "overrides did not converge")
    elif name == "custom":
        host.custom_code(op[1])
        if "!" in op[1].split("\n") and "~" not in op[1].split("\n"):
            host.resume()
    elif name == "write_settings":
        host.write_settings(op[1])
    elif name == "set_zero":
        host.set_zero()
    elif name == "home":
        host.home()
    elif name == "unlock":
        host.unlock()
    elif name == "safety_door":
        host.safety_door()
        host.send_command("G4 P0")  # what follows the door command on the line
        wait(lambda: device.lines, 5)
        # a board in Door (0x84) waits for the host to see it before cycle start
        wait(lambda: host.status == "Door" or not device.hold, 5)
        host.resume()
    elif name.startswith("job"):
        path = _job_file(tmp_dir, op[1], f"job{k}.nc")
        host.load_gcode(path)
        if name == "job":
            host.run_job(passes=op[2])
            wait(lambda: FOOTER in device.lines or not host.job_running, 30, "job did not end")
        elif name == "job_error":
            device.error_rules = [(r"^G1", 20)]
            host.run_job()
            wait(lambda: not host.job_running, 30, "job did not end")
            device.error_rules = []
        elif name == "job_resume":
            host.resume_job(op[2])
            wait(lambda: not host.job_running, 30, "resumed job did not end")
        else:
            device.set_auto_ack(False)
            host.run_job()
            wait(lambda: device.lines or not host.job_running, 5)
            # the board acknowledges nothing: let the host fill the RX buffer first
            wait(lambda: stays_true(lambda n=len(device.lines): len(device.lines) == n, 0.5), 10)
            fill[0] = device.rx_used
            if host.job_running:
                if name == "job_hold":
                    wait(lambda: host.status == "Run", 5)
                    host.feed_hold()
                    wait(lambda: host.status == "Hold", 5)
                    device.set_auto_ack(True)
                    host.resume()
                elif name == "job_reset":
                    host.soft_reset()
                    wait(lambda: device.resets >= 1, 5)
                elif name == "job_abort":
                    host.abort_job()
                elif name == "job_alarm":
                    device.alarm_now(1)  # the board drops its buffer: no more oks for it
                    wait(lambda: host.status == "Alarm", 5)
                    host.soft_reset()  # what the user does to recover
                    wait(lambda: device.resets >= 1, 5)
            device.set_auto_ack(True)
            if name == "job_alarm":
                wait(lambda: host.status == "Alarm" and not host.job_running, 10)
                host.unlock()


def _snapshot(host):
    return {"status": host.status, "job_running": host.job_running, "job_errors": host.job_errors,
            "issues": list(host.issues), "buffer_size": host.buffer_size}


def play(kind: str, scenario: Scenario, tmp_dir) -> list[dict]:
    """Play ``scenario`` against host ``kind`` (``csharp`` or ``rust``); one trace per op
    plus one for the connection."""
    from .fake_grbl import FakeGrbl
    from .host import CSharpHost, RustHost, wait
    from .jobs import settle
    from .links import PtyLink

    if kind == "csharp":
        from . import bootstrap

        bootstrap.reset_csharp_state()
        host = CSharpHost()
    else:
        host = RustHost()
    device = FakeGrbl(**scenario.device)
    link = PtyLink(device)
    traces = []

    def cut(op, error="", fill=None):
        # The exact peak of RX buffer use is deterministic only when the board does not
        # acknowledge (job_fill); with instant acks it depends on thread timing, so
        # elsewhere only the bound is compared (peak within the buffer, no overflow).
        snap = _snapshot(host)
        t = {"op": op, "lines": list(device.lines), "realtime": [b for b in device.realtime if b != 0x3F],
             "rx_within_buffer": device.max_rx_used <= snap["buffer_size"], "rx_fill": fill,
             "overflows": device.overflows, "error": error, **snap}
        device.lines.clear()
        device.realtime.clear()
        device.max_rx_used = 0
        return t

    try:
        for k, v in scenario.options.items():
            host.set_option(k, v)
        host.connect(link.path)
        settle(host, device)
        wait(lambda: host.status == "Idle", 5)
        traces.append(cut(("connect",)))
        for k, op in enumerate(scenario.ops):
            error = ""
            fill = [None]
            try:
                _run_op(host, device, op, tmp_dir, k, fill)
            except Exception as exc:  # recorded and compared by kind
                if "did not" in str(exc):
                    raise
                error = _error_kind(exc)
            _quiet(host, device)
            traces.append(cut(op, error, fill[0]))
    finally:
        link.close()
        host.close()
    return traces
