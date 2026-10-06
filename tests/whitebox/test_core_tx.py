"""GrblCore transmit path and job lifecycle, driven step by step (no threads).

``rig.pump()`` = send everything the core allows, let the fake device answer,
parse the answers; repeat until quiescent.
"""

import pytest

import System
from LaserGRBL import GrblCommand, GrblConfST, GrblCore, Settings
from Tools import HiResTimer, TimingBase

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus, load_file_sync

V = GrblCore.GrblVersionInfo
Issue = GrblCore.DetectedIssue
SM = GrblCore.StreamingMode


@pytest.fixture
def r(rigs):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    rig.open_stepped(MacStatus.Idle)
    return rig


@pytest.fixture
def gcode(tmp_path):
    def make(lines, name="job.nc"):
        p = tmp_path / name
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    return make


def enqueue(rig, *lines):
    for ln in lines:
        rig.core.EnqueueCommand(GrblCommand(ln))


def age(elapsed_from_event, seconds):
    """Make a Tools.ElapsedFromEvent look started ``seconds`` ago."""
    start = TimingBase.TimeFromApplicationStartup() - System.TimeSpan.FromSeconds(seconds)
    cu.set(elapsed_from_event, "starttime", start)
    cu.set(elapsed_from_event, "started", True)


def load(rig, path):
    load_file_sync(rig.core.LoadedFile, path)


# ---------------------------------------------------------------- buffer accounting
def test_stream_waits_when_rx_buffer_full(r):
    r.device.auto_ack = False
    enqueue(r, *["G1 X100.000 Y100.000"] * 10)  # 19 bytes on the wire each
    while r.can_send():
        r.send_line()
    assert r.pending.Count == 6 and r.core.UsedBuffer == 114
    assert r.core.FreeBuffer == 13
    r.link.pump()
    assert r.device.max_rx_used == 114 and r.device.overflows == 0
    r.ack(1)
    assert r.can_send()
    r.send_line()
    assert not r.can_send()


def test_line_that_exactly_fills_buffer_is_sent(r):
    r.device.auto_ack = False
    enqueue(r, "G1X" + "1" * 123)  # 127 bytes with the newline
    assert r.can_send()
    r.send_line()
    assert r.core.UsedBuffer == 127 and r.core.FreeBuffer == 0


def test_line_bigger_than_buffer_is_never_sent(r):
    enqueue(r, "G1X" + "1" * 124)  # 128 bytes
    assert not r.can_send()
    r.step_tx()
    assert r.pending.Count == 0 and r.queue.Count == 1


def test_all_lines_streamed_in_order(r):
    lines = [f"G1 X{i} Y{i * 2}" for i in range(50)]
    enqueue(r, *lines)
    r.pump()
    assert r.device.lines == [ln.replace(" ", "") for ln in lines]
    assert r.device.max_rx_used <= 127 and r.queue.Count == 0 and r.pending.Count == 0
    assert all(c.Status == GrblCommand.CommandStatus.ResponseGood for c in r.sent_rows())


def test_synchronous_mode_sends_one_line_at_a_time(r):
    Settings.SetObject("Streaming Mode", SM.Synchronous)
    r.device.auto_ack = False
    enqueue(r, "G0 X1", "G0 X2")
    r.send_line()
    assert not r.can_send()
    r.ack(1)
    assert r.can_send()


def test_eeprom_write_is_sent_synchronously(r):
    r.device.auto_ack = False
    enqueue(r, "$110=500", "G0 X1")
    r.send_line()
    assert not r.can_send()  # buffered mode, but waiting for the EEPROM write
    r.ack(1)
    assert r.can_send()


def test_send_error_is_logged_and_command_dropped(r):
    enqueue(r, "G0 X1")
    r.com.WriteError = System.IO.IOException("boom")
    r.send_line()
    # the command was moved to pending/sent before the write failed
    assert r.pending.Count == 1 and r.queue.Count == 0
    assert r.core.UsedBuffer == len("G0X1\n")


def test_sent_command_window(r):
    enqueue(r, "G0 X1", "G0 X2", "G0 X3")
    r.pump()
    assert r.core.Executed == 3
    assert [str(x.GetDecodedMessage()) for x in r.core.SentCommand(1, 5)] == ["G0 X2", "G0 X3"]
    assert [str(x.GetDecodedMessage()) for x in r.core.SentCommand(10, 1)] == ["G0 X3"]
    assert list(r.core.SentCommand(0, 0)) == []


def test_enqueue_stores_a_clone(r):
    c = GrblCommand("G0 X1")
    r.core.EnqueueCommand(c)
    assert not System.Object.ReferenceEquals(r.queue.Peek(), c)
    assert r.core.QueueEmpty is False


# ---------------------------------------------------------------- job lifecycle
def test_run_program_sends_header_file_and_footer(r, gcode):
    load(r, gcode(["G1 X10 F1000", "G1 Y10", "G1 X0"]))
    assert r.core.CanSendFile
    r.core.RunProgram(None)
    assert r.core.InProgram and r.core.ProgramTarget == 4  # header + 3 lines
    r.pump()
    # comments are stripped by BuildHelper at send time (it rewrites the command text)
    assert r.device.lines == ["G90", "G1X10F1000", "G1Y10", "G1X0", "G0X0Y0Z0"]
    assert not r.core.InProgram
    assert r.core.ProgramExecuted == 4 and r.core.ProgramSent == 4
    assert "ended" in r.events
    assert any(t.startswith("[3 lines, 0 errors,") for t in r.sent_texts())


def test_run_program_counts_errors(r, gcode):
    r.device.error_rules = [("Y10", 33)]
    load(r, gcode(["G1 X10 F1000", "G1 Y10"]))
    r.core.RunProgram(None)
    r.pump()
    assert any(t.startswith("[2 lines, 1 errors,") for t in r.sent_texts())


def test_custom_header_footer_expressions_and_immediate_codes(r, gcode):
    Settings.SetObject("GCode.CustomHeader", "M3 S[$30/2]\r\n0x85\r\n\r\nG0 X[left] Y[bottom]")
    Settings.SetObject("GCode.CustomFooter", "M5\r\n!")
    load(r, gcode(["G0 X5 Y6", "M3 S10", "G1 X15 Y26 F100"]))
    r.core.RunProgram(None)
    r.pump()
    assert r.device.lines[:2] == ["M3S500.000", "G0X5.000Y6.000"]
    assert r.device.lines[-1] == "M5"
    assert 0x85 in r.device.realtime and 0x21 in r.device.realtime  # 0x85 from header, '!' from footer
    assert cu.get(r.core, "mHoldByUserRequest")


def test_loop_count_repeats_program_with_passes_code(r, gcode):
    load(r, gcode(["G1 X1 F100"]))
    r.core.LoopCount = System.Decimal(2)
    r.core.RunProgram(None)
    r.pump()
    lines = r.device.lines
    assert lines.count("G1X1F100") == 2
    # the default passes code is 4 comment-only lines: each one is streamed as an
    # empty line ("\n") and costs an "ok" round trip (FINDINGS.md F-17)
    assert lines == ["G90", "G1X1F100", "", "", "", "", "G1X1F100", "G0X0Y0Z0"]
    assert float(str(r.core.LoopCount)) == 1
    assert "loop:1" in r.events and r.events.count("ended") == 2


def test_loop_count_in_check_mode_runs_once(r, gcode):
    load(r, gcode(["G1 X1 F100"]))
    r.set_status(MacStatus.Check)
    r.core.LoopCount = System.Decimal(3)
    r.core.RunProgram(None)
    r.pump()
    assert r.device.lines.count("G1X1F100") == 1


def test_run_program_requires_idle_connected_and_empty_queue(r, gcode):
    r.core.RunProgram(None)  # no program: nothing happens
    assert r.queue.Count == 0
    load(r, gcode(["G0 X1"]))
    enqueue(r, "G0 X9")
    assert not r.core.CanSendFile
    r.core.RunProgram(None)
    assert r.queue.Count == 1


def test_run_program_swallows_exceptions(r, gcode):
    load(r, gcode(["G0 X1"]))
    Settings.SetObject("GCode.CustomHeader", None)  # ExecuteCustomCode(null) throws
    r.core.RunProgram(None)
    assert not cu.get(r.core, "mDoingSend")


def test_abort_program_flushes_queue_and_turns_laser_off(r, gcode):
    r.device.auto_ack = False
    load(r, gcode([f"G1 X{i} F100" for i in range(20)]))
    r.core.RunProgram(None)
    r.set_status(MacStatus.Run)
    while r.can_send():
        r.send_line()
    assert r.core.CanAbortProgram
    r.core.AbortProgram()
    assert r.queue_texts() == ["M5"]
    assert not r.core.InProgram and r.tp.LastIssue == Issue.ManualAbort
    assert not any(e.startswith("issue") for e in r.events)  # user issues are not reported


def test_abort_without_program_is_ignored(r):
    assert not r.core.CanAbortProgram
    r.core.AbortProgram()
    assert r.queue.Count == 0


def test_abort_exception_is_swallowed(r, gcode):
    load(r, gcode(["G0 X1"]))
    enqueue(r, "G0 X2")
    saved = cu.get(r.core, "mTP")
    cu.set(r.core, "mTP", None)
    r.core.AbortProgram()
    cu.set(r.core, "mTP", saved)
    assert r.queue.Count == 1


def test_resume_from_position_rebuilds_state(r, gcode):
    load(r, gcode(["G21", "G1 X10 Y5 F600 S300", "M3", "X20", "G0 X30", "G1 Y40"]))
    r.core.LoadedFile  # noqa: B018
    cu.call(r.core, "ContinueProgramFromKnown", 3, False, False)
    q = r.queue_texts()
    assert q[0] == "G90"
    assert q[1] == "M5 G0 X10 Y5 Z0 F600 S300"
    # settled modal groups; G21/G20 (units) are not tracked at all (FINDINGS.md F-18)
    assert q[2] == "M3"
    assert q[3:] == ["G1 X20", "G0 X30", "G1 Y40"]
    assert "[resume from #4]" in r.sent_texts()
    # Sent/Executed start at the resume position minus the 3 injected commands
    assert r.core.InProgram and r.core.ProgramSent == 0 and r.core.ProgramExecuted == 0


def test_resume_with_homing_and_work_offset(r, gcode):
    load(r, gcode(["G1 X10 F100", "G1 X20"]))
    r.rx("<Idle|MPos:15,5,0|WCO:5,0,0>")
    cu.call(r.tp, "JobStart", r.core.LoadedFile, r.queue, True)
    r.rx("<Idle|MPos:15,5,0|WCO:5,0,0>")  # remembered while in program
    r.tp.JobEnd(True)
    cu.call(r.core, "ContinueProgramFromKnown", 1, True, True)
    q = r.queue_texts()
    assert q[0] == "$H"
    assert q[1] == "G92 X-5 Y0 Z0"  # homing: position 0 minus the last WCO
    # no settled modal group -> an empty command is enqueued (FINDINGS.md F-19)
    assert q[4:] == ["", "G1 X20"]


def test_resume_position_beyond_file_end(r, gcode):
    load(r, gcode(["G0 X1"]))
    cu.call(r.core, "ContinueProgramFromKnown", 5, False, False)
    assert r.queue_texts()[:2] == ["G90", "M5 G0 X1 Y0 Z0 F0 S0"]


def test_resume_first_movement_without_g_gets_motion_mode(r, gcode):
    load(r, gcode(["G1 X1 F100", "X2", "X3"]))
    cu.call(r.core, "ContinueProgramFromKnown", 1, False, False)
    assert r.queue_texts()[-2:] == ["G1 X2", "X3"]


def test_repeat_on_error_resends_failed_line_up_to_three_times(r, gcode):
    Settings.SetObject("Streaming Mode", SM.RepeatOnError)
    r.device.error_rules = [("X5", 20)]
    load(r, gcode(["G1 X1 F100", "G1 X5", "G1 X9"]))
    r.core.RunProgram(None)
    r.pump()
    assert r.device.lines.count("G1X5") == 4
    retries = [t for t in r.sent_texts() if "Retry" in t]
    assert retries == ["G1 X5 (Retry 1)", "G1 X5 (Retry 2)", "G1 X5 (Retry 3)"]
    assert r.device.lines[-2] == "G1X9"


# ---------------------------------------------------------------- immediate commands
def realtime_after(rig, fn):
    before = len(rig.device.realtime)
    fn()
    rig.link.pump()
    return rig.device.realtime[before:]


def test_feed_hold_and_resume(r):
    assert realtime_after(r, lambda: r.core.FeedHold(False)) == []  # not running
    r.set_status(MacStatus.Run)
    assert realtime_after(r, lambda: r.core.FeedHold(False)) == [0x21]
    assert cu.get(r.core, "mHoldByUserRequest")
    assert realtime_after(r, lambda: r.core.CycleStartResume(False)) == []  # not in hold
    r.set_status(MacStatus.Hold)
    assert realtime_after(r, lambda: r.core.CycleStartResume(False)) == [0x7E]
    r.set_status(MacStatus.Door)
    assert realtime_after(r, lambda: r.core.CycleStartResume(False)) == [0x7E]


def test_safety_door_sends_legacy_at_sign(r):
    # '@' was the safety-door command of Grbl 0.9; Grbl 1.1 uses 0x84 and treats
    # '@' as a normal character of the next line (FINDINGS.md F-20)
    assert realtime_after(r, r.core.SafetyDoor) == []
    assert bytes(r.device.raw) == b"@"


def test_query_position_sends_question_mark(r):
    assert realtime_after(r, lambda: cu.call(r.core, "QueryPosition")) == [0x3F]


def test_send_immediate_only_when_port_open(r):
    r.com.ForceOpen(False)
    assert realtime_after(r, lambda: r.core.SendImmediate(0x18, False)) == []


def test_send_immediate_write_error_is_swallowed(r):
    r.com.WriteError = System.IO.IOException("x")
    r.core.SendImmediate(0x3F, True)


def test_grbl_reset_during_program_flags_manual_reset(r, gcode):
    load(r, gcode(["G0 X1", "G0 X2"]))
    r.core.RunProgram(None)
    r.set_status(MacStatus.Run)
    r.core.TOverrideS = 120
    assert realtime_after(r, r.core.GrblReset) == [0x18]
    assert r.tp.LastIssue == Issue.ManualReset and r.queue.Count == 0
    assert r.core.TOverrideS == 100 and r.core.UsedBuffer == 0 and r.sent.Count == 0


def test_grbl_reset_not_allowed_when_disconnected(rigs):
    rig = rigs()
    assert not rig.core.CanResetGrbl
    rig.core.GrblReset()
    rig.link.pump()
    assert rig.device.realtime == []


def test_execute_custom_code_handles_immediates_and_expressions(r):
    r.core.JogStep = System.Decimal(2.5)
    r.core.JogSpeed = 1000
    cu.call(r.core, "ExecuteCustomCode", "?\r\n~\r\nctrl-x\r\n0x9e\r\n0xZZ\r\nG1 X[jogstep*2] F[jogspeed]\r\n$H")
    r.link.pump()
    assert r.device.realtime == [0x3F, 0x7E, 0x18, 0x9E]
    assert r.queue_texts() == ["0xZZ", "G1 X5.000 F1000.000", "$H"]


def test_evaluate_expression_variables(r, gcode):
    load(r, gcode(["G0 X10 Y20", "M3 S100", "G1 X30 Y50 F100"]))
    GrblCore.Configuration = GrblConfST(V(1, 1), _dict({30: "255", 110: "abc", 130: "300"}))
    r.rx("<Idle|MPos:3,4,5|WCO:1,2,3>")
    ev = lambda s: str(cu.call(r.core, "EvaluateExpression", s))  # noqa: E731
    assert ev("[left] [right] [top] [bottom]") == "10.000 30.000 50.000 20.000"
    assert ev("[width] [height]") == "20.000 30.000"
    assert ev("[$30] [$130]") == "255.000 300.000"
    assert ev("[WCO.X] [MPos.Z]") == "1.000 5.000"
    # WPos.* are bound to the machine position (FINDINGS.md F-06)
    assert ev("[WPos.X]") == "3.000"
    assert ev("[nope+]") == "[nope+]"  # evaluation errors leave the text untouched


def test_evaluate_expression_default_spindle_max_and_empty_drawing(r):
    ev = lambda s: str(cu.call(r.core, "EvaluateExpression", s))  # noqa: E731
    assert ev("S[$30]") == "S1000.000"
    assert ev("X[left]") == "X0.000"


def _dict(d):
    out = System.Collections.Generic.Dictionary[int, str]()
    for k, v in d.items():
        out[k] = v
    return out


# ---------------------------------------------------------------- TX loop housekeeping
def test_tx_loop_sends_and_queries_status(r):
    enqueue(r, "G0 X1")
    qt = cu.get(r.core, "QueryTimer")
    qt.Start()
    age(cu.get(qt, "crono"), 10)
    r.step_tx()
    r.link.pump()
    assert r.device.lines == ["G0X1"] and r.device.realtime == [0x3F]


def test_tx_loop_exception_is_logged(r):
    saved = cu.get(r.core, "mPending")
    cu.set(r.core, "mPending", None)
    r.step_tx()
    cu.set(r.core, "mPending", saved)


def test_connect_timeout_closes_port(r):
    r.set_status(MacStatus.Disconnected)
    r.set_status(MacStatus.Connecting)
    cu.set(r.core, "connectStart", System.Int64(HiResTimer.TotalMilliseconds - 20000))
    r.step_tx()
    assert list(r.com.CloseLog) == [True]
    r.com.ForceOpen(False)
    r.step_tx()  # port already closed: nothing more to do
    assert list(r.com.CloseLog) == [True]


def test_hang_detected_when_no_status_for_too_long(r, gcode):
    load(r, gcode(["G0 X1"]))
    r.core.RunProgram(None)
    r.set_status(MacStatus.Run)
    age(cu.get(r.core, "debugLastStatusDelay"), 60)
    r.step_tx()
    assert "issue:StopResponding" in r.events


def test_buffer_stuck_is_unlocked_when_grbl_reports_empty_buffer(r, gcode):
    load(r, gcode(["G0 X1", "G0 X2"]))
    r.core.RunProgram(None)
    r.device.auto_ack = False
    r.set_status(MacStatus.Run)
    while r.can_send():
        r.send_line()
    age(cu.get(r.core, "debugLastMoveOrActivityDelay"), 60)
    assert r.core.IsBufferStuck()
    r.rx("<Run|MPos:0,0,0|Bf:15,127>")  # status parsing restarts the activity timer
    age(cu.get(r.core, "debugLastMoveOrActivityDelay"), 60)
    cu.call(r.core, "HandleMissingOK")
    assert r.pending.Count == 0
    assert "Unlock from buffer stuck!" in r.sent_texts()


def test_manual_buffer_stuck_unlock(r, gcode):
    load(r, gcode(["G0 X1"]))
    r.core.RunProgram(None)
    r.device.auto_ack = False
    r.set_status(MacStatus.Run)
    r.send_line()
    r.core.UnlockFromBufferStuck(False)
    assert r.pending.Count == 1  # not stuck yet (recent activity)
    age(cu.get(r.core, "debugLastMoveOrActivityDelay"), 60)
    r.core.UnlockFromBufferStuck(False)
    assert r.pending.Count == 0


def test_auto_cooling_pauses_and_resumes(r, gcode):
    GrblCore.Configuration = GrblConfST(V(1, 1), _dict({32: "1"}))
    Settings.SetObject("AutoCooling", True)
    Settings.SetObject("AutoCooling TOn", System.TimeSpan.FromMilliseconds(1))
    Settings.SetObject("AutoCooling TOff", System.TimeSpan.FromHours(1))
    assert r.core.AutoCooling and r.core.SupportAutoCooling
    load(r, gcode(["G0 X1"]))
    r.device.auto_ack = False
    r.core.RunProgram(None)
    r.set_status(MacStatus.Run)
    cu.set(r.tp, "mGlobalStart", System.Int64(HiResTimer.TotalMilliseconds - 1000))
    assert realtime_after(r, r.step_tx) == [0x21]
    r.set_status(MacStatus.Cooling)
    Settings.SetObject("AutoCooling TOn", System.TimeSpan.FromHours(2))
    assert realtime_after(r, r.step_tx) == [0x7E]
    assert r.core.AutoCoolingOn.TotalHours == 2 and r.core.AutoCoolingOff.TotalHours == 1


def test_auto_cooling_without_laser_mode_does_nothing(r):
    GrblCore.Configuration = GrblConfST(V(1, 1), _dict({32: "0"}))
    cu.call(r.core, "StartCooling")
    cu.call(r.core, "ResumeCooling")
    r.link.pump()
    assert r.device.realtime == []
    assert not r.core.SupportAutoCooling


# ---------------------------------------------------------------- permissions
def test_can_flags_by_state(r, gcode):
    c = r.core
    assert c.CanImportExport and c.CanSendManualCommand and c.CanUnlock and c.CanReadWriteConfig
    assert not c.CanDoZeroing  # work position is zero
    assert c.CanDoHoming  # default config: homing enabled
    r.rx("<Idle|MPos:1,0,0>")
    assert c.CanDoZeroing
    r.set_status(MacStatus.Alarm)
    assert c.CanUnlock and c.CanDoHoming and not c.CanImportExport and c.CanReadWriteConfig
    r.set_status(MacStatus.Run)
    assert c.CanFeedHold and not c.CanUnlock and not c.CanReadWriteConfig
    load(r, gcode(["G0 X1"]))
    assert c.CanAbortProgram and c.CanLoadNewFile
    r.set_status(MacStatus.Disconnected)
    assert not c.IsConnected and not c.CanResetGrbl and not c.CanSendManualCommand


def test_homing_unlock_zero_commands(r):
    cu.call(r.core, "GrblHoming")
    cu.call(r.core, "GrblUnlock")
    cu.call(r.core, "SetNewZero")  # WorkPosition is zero: not allowed
    r.rx("<Idle|MPos:1,0,0>")
    cu.call(r.core, "SetNewZero")
    cu.call(r.core, "SendHomingCommand")
    cu.call(r.core, "SendUnlockCommand")
    assert r.queue_texts() == ["$H", "$X", "G92 X0 Y0 Z0", "$H", "$X"]


def test_homing_not_allowed_when_disabled(r):
    GrblCore.Configuration = GrblConfST(V(1, 1), _dict({22: "0"}))
    cu.call(r.core, "GrblHoming")
    assert r.queue.Count == 0


def test_close_com_during_program_flags_disconnect(r, gcode):
    load(r, gcode(["G0 X1", "G0 X2"]))
    r.core.RunProgram(None)
    r.set_status(MacStatus.Run)
    r.core.CloseCom(False)
    assert "issue:UnexpectedDisconnect" in r.events
    assert r.core.MachineStatus == MacStatus.Disconnected and list(r.com.CloseLog) == [True]


def test_close_com_by_user_is_not_reported(r, gcode):
    load(r, gcode(["G0 X1"]))
    r.core.RunProgram(None)
    r.set_status(MacStatus.Run)
    r.core.CloseCom(True)
    assert r.tp.LastIssue == Issue.ManualDisconnect
    assert not any(e.startswith("issue") for e in r.events)


def test_close_com_exception_is_swallowed(r):
    saved = cu.get(r.core, "com")
    cu.set(r.core, "com", None)
    r.core.CloseCom(True)
    cu.set(r.core, "com", saved)
    assert r.core.MachineStatus == MacStatus.Idle


def test_exiting_closes_everything(r):
    cu.call(r.core, "Exiting")
    assert r.core.MachineStatus == MacStatus.Disconnected


def test_exiting_tolerates_failures(r):
    cu.set(r.core, "TX", None)
    cu.set(r.core, "RX", None)
    cu.call(r.core, "Exiting")


def test_open_com_failure_reports_and_disconnects(rigs):
    rig = rigs()
    rig.com.FailOpen = System.IO.IOException("port busy")
    # after logging and closing, OpenCom shows a MessageBox, which needs a display:
    # under the headless harness that last step throws (see COVERAGE.md)
    with pytest.raises(Exception):
        rig.core.OpenCom()
    assert rig.core.MachineStatus == MacStatus.Disconnected
    assert list(rig.com.CloseLog) == [True]
    assert rig.core.FailedConnectionCount == 1


def test_write_config_is_silently_skipped_when_not_idle(r):
    r.set_status(MacStatus.Run)
    lst = System.Collections.Generic.List[GrblConfST.GrblConfParam]()
    lst.Add(GrblConfST.GrblConfParam(110, "1"))
    r.core.WriteConfig(lst)  # no exception, nothing queued
    r.core.RefreshConfig(GrblCore.RefreshCause.OnDialog)  # same: only logged
    assert r.queue.Count == 0 and r.device.lines == []


def test_job_started_during_connect_time_refresh_is_lost(r, gcode):
    # While RefreshConfig/RefreshMachineInfo wait for $$/$I they point mQueuePtr to a
    # private queue; RunProgram enqueues there, and the finally block that restores
    # the pointer drops whatever was not sent yet (FINDINGS.md F-30). This test
    # reproduces the pointer swap deterministically instead of racing the threads.
    load(r, gcode(["G0 X1", "G0 X2"]))
    real = cu.get(r.core, "mQueue")
    temp = System.Collections.Generic.Queue[GrblCommand]()
    cu.set(r.core, "mQueuePtr", temp)  # what the refresh does while waiting
    assert r.core.CanSendFile  # CanSendFile only looks at the real queue
    r.core.RunProgram(None)
    assert temp.Count == 3 and real.Count == 0
    cu.set(r.core, "mQueuePtr", real)  # what its finally block does
    assert r.core.InProgram and r.queue.Count == 0
    r.pump()
    assert r.device.lines == [] and r.core.InProgram  # the job never streams nor ends
