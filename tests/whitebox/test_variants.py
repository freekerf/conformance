"""Firmware variants: MarlinCore, SmoothieCore, VigoCore."""

import pytest

import System
from LaserGRBL import Firmware, GrblCommand, GrblCore, MarlinCore, Settings, SmoothieCore, VigoCore
from Tools import TimingBase

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus, load_file_sync

SM = GrblCore.StreamingMode
V = GrblCore.GrblVersionInfo


def age(ev, seconds):
    cu.set(ev, "starttime", TimingBase.TimeFromApplicationStartup() - System.TimeSpan.FromSeconds(seconds))
    cu.set(ev, "started", True)


@pytest.fixture
def gcode(tmp_path):
    def make(lines):
        p = tmp_path / "v.nc"
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    return make


def realtime_after(rig, fn):
    before = len(rig.device.realtime)
    fn()
    rig.link.pump()
    return rig.device.realtime[before:]


# ---------------------------------------------------------------- Marlin
@pytest.fixture
def marlin(rigs):
    rig = rigs(MarlinCore)
    rig.open_stepped(MacStatus.Idle)
    return rig


def test_marlin_capabilities(marlin):
    c = marlin.core
    assert c.Type == Firmware.Marlin and c.CurrentStreamingMode == SM.Synchronous
    assert not c.UIShowGrblConfig and not c.UIShowUnlockButtons and not c.SupportTrueJogging


def test_marlin_queries_position_with_m114_unless_running(marlin):
    cu.call(marlin.core, "QueryPosition")
    marlin.link.pump()
    assert marlin.device.lines == ["M114"]
    marlin.set_status(MacStatus.Run)
    cu.call(marlin.core, "QueryPosition")
    marlin.link.pump()
    assert marlin.device.lines == ["M114"]


def test_marlin_position_report_sets_idle_and_position(marlin):
    marlin.set_status(MacStatus.Run)
    marlin.rx("X:10.00 Y:2.50 Z:-1.00 E:0.00 Count X:1600 Y:0 Z:0")
    mp = marlin.core.MachinePosition
    assert (mp.X, mp.Y, mp.Z) == (10, 2.5, -1)
    assert marlin.core.MachineStatus == MacStatus.Idle


def test_marlin_malformed_position_report_is_swallowed(marlin):
    marlin.rx("X:abc")
    assert marlin.core.MachinePosition.X == 0


def test_marlin_status_parsing(marlin):
    cu.call(marlin.core, "ParseMachineStatus", "busy")
    assert marlin.core.MachineStatus == MacStatus.Disconnected  # anything without "ok"
    cu.call(marlin.core, "ParseMachineStatus", "ok")
    assert marlin.core.MachineStatus == MacStatus.Idle


def test_marlin_reports_run_while_in_program_and_idle_at_end(marlin, gcode):
    load_file_sync(marlin.core.LoadedFile, gcode(["G1 X1 F100"]))
    marlin.core.RunProgram(None)
    cu.call(marlin.core, "ParseMachineStatus", "ok")
    assert marlin.core.MachineStatus == MacStatus.Run
    marlin.pump()
    assert not marlin.core.InProgram and marlin.core.MachineStatus == MacStatus.Idle  # ForceStatusIdle


def test_marlin_no_reset_no_unlock_no_config(marlin):
    assert realtime_after(marlin, marlin.core.GrblReset) == []
    cu.call(marlin.core, "SendUnlockCommand")
    marlin.core.RefreshConfig(GrblCore.RefreshCause.OnDialog)
    marlin.core.RefreshMachineInfo()
    assert marlin.queue.Count == 0 and marlin.device.lines == []


def test_marlin_hang_detection_uses_activity_timer(marlin, gcode):
    load_file_sync(marlin.core.LoadedFile, gcode(["G1 X1 F100"]))
    marlin.core.RunProgram(None)
    marlin.set_status(MacStatus.Run)
    age(cu.get(marlin.core, "debugLastStatusDelay"), 60)
    cu.call(marlin.core, "DetectHang")
    assert "issue:StopResponding" not in marlin.events  # recent activity
    age(cu.get(marlin.core, "debugLastMoveOrActivityDelay"), 60)
    cu.call(marlin.core, "DetectHang")
    assert "issue:StopResponding" in marlin.events


def test_marlin_streams_synchronously(marlin):
    marlin.device.auto_ack = False
    marlin.core.EnqueueCommand(GrblCommand("G0 X1"))
    marlin.core.EnqueueCommand(GrblCommand("G0 X2"))
    marlin.send_line()
    assert not marlin.can_send()


# ---------------------------------------------------------------- Smoothie
@pytest.fixture
def smoothie(rigs):
    rig = rigs(SmoothieCore)
    rig.open_stepped(MacStatus.Idle)
    return rig


def test_smoothie_capabilities(smoothie):
    c = smoothie.core
    assert c.Type == Firmware.Smoothie and c.CurrentStreamingMode == SM.Synchronous
    assert not c.UIShowGrblConfig and not c.UIShowUnlockButtons and not c.SupportTrueJogging


def test_smoothie_start_skips_soft_reset_and_sends_newline_then_query(smoothie):
    cu.call(smoothie.core, "StartTX")
    smoothie.link.pump()
    assert bytes(smoothie.device.raw) == b"\n?"
    assert smoothie.device.realtime == [0x3F]


def test_grbl_start_sends_soft_reset_then_query(rigs):
    rig = rigs()
    rig.open_stepped(MacStatus.Idle)
    cu.call(rig.core, "StartTX")
    rig.link.pump()
    assert rig.device.realtime[:2] == [0x18, 0x3F]


def test_grbl_start_without_reset_setting(rigs):
    Settings.SetObject("Reset Grbl On Connect", False)
    rig = rigs()
    rig.open_stepped(MacStatus.Idle)
    cu.call(rig.core, "StartTX")
    rig.link.pump()
    assert rig.device.realtime == [0x3F]


def test_smoothie_reset_writes_reset_command(smoothie):
    smoothie.core.GrblReset()
    smoothie.link.pump()
    assert smoothie.device.lines == ["reset"]


def test_smoothie_parses_feed_and_spindle_from_f_field(smoothie):
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    smoothie.rx("<Idle|MPos:0,0,0|F:1200.0,30.0>")
    assert (smoothie.core.CurrentF, smoothie.core.CurrentS) == (1200, 30)


def test_smoothie_unlock_is_noop(smoothie):
    cu.call(smoothie.core, "SendUnlockCommand")
    assert smoothie.queue.Count == 0


# ---------------------------------------------------------------- Vigo
@pytest.fixture
def vigo(rigs):
    rig = rigs(VigoCore)
    rig.open_stepped(MacStatus.Idle)
    return rig


def test_vigo_capabilities(vigo):
    assert vigo.core.Type == Firmware.VigoWork and vigo.core.BufferSize == 127
    cu.set(vigo.core, "mAutoBufferSize", 1024)
    assert vigo.core.BufferSize == 127


def test_vigo_queries_with_0x88(vigo):
    assert realtime_after(vigo, lambda: cu.call(vigo.core, "QueryPosition")) == [0x88]


def test_vigo_outside_job_marks_commands_ok_immediately(vigo):
    vigo.device.auto_ack = False
    vigo.core.EnqueueCommand(GrblCommand("G0 X1"))
    vigo.send_line()
    c = vigo.pending.Peek()
    assert c.Status == GrblCommand.CommandStatus.ResponseGood
    # ...but it stays in the pending queue and the buffer is not counted (FINDINGS.md F-08)
    assert vigo.pending.Count == 1 and vigo.core.UsedBuffer == 0


def test_vigo_job_wraps_program_and_uses_sbuf_counters(vigo, gcode):
    vigo.device.auto_ack = False
    load_file_sync(vigo.core.LoadedFile, gcode(["G1 X1 F100", "G1 X2"]))
    vigo.core.RunProgram(None)
    assert vigo.queue_texts()[:2] == [">Ofk9gsd8IKjKBahP0OGS9BrhZCPeWCBALCbyGf", "G90 (use absolute coordinates)"]
    while vigo.can_send():
        vigo.send_line()
    sent = vigo.pending.Count
    assert sent == 4 and vigo.core.UsedBuffer > 0
    vigo.rx("<VSta:2|SBuf:4,3,1|LTC:0>")  # 3 managed, 1 error since the start
    assert vigo.pending.Count == 0
    statuses = [str(c.Status) for c in vigo.sent_rows() if cu.type_name(c) == "GrblCommand"]
    assert statuses == ["ResponseGood", "ResponseGood", "ResponseGood", "ResponseBad"]
    assert not vigo.core.InProgram and any(t.startswith("[2 lines, 1 errors") for t in vigo.sent_texts())
    # end of job: footer + Vigo trailer were queued by OnJobEnd
    assert vigo.queue_texts()[-2:] == ["G0X0Y0M5", ">NPredMjdFaeaJajf6OHy:hkRUygcpBXwtV"]


def test_vigo_sbuf_counter_reset_and_job_end_state(vigo):
    vigo.rx("<VSta:2|SBuf:10,10,0>")
    vigo.rx("<VSta:0|SBuf:2,2,0>")  # received went backwards: counters restart from 0
    assert cu.get(vigo.core, "mOldManaged") == 2
    assert not cu.get(vigo.core, "injob")


def test_vigo_malformed_status_is_swallowed(vigo):
    vigo.rx("<VSta:x|SBuf:1,1,1>")
    assert cu.get(vigo.core, "mOldManaged") == 0


def test_vigo_other_lines_use_grbl_parser(vigo):
    vigo.rx("Grbl 1.1f ['$' for help]")
    assert str(vigo.core.GrblVersion) == "1.1f"
