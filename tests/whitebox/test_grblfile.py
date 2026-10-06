"""GrblFile (G-code part): load, analysis (ranges, timing), quadrant, save."""

import pytest

import System
from System.Collections.Generic import Dictionary
from LaserGRBL import Firmware, GrblCommand, GrblConfST, GrblCore, GrblFile, ProgramRange, Settings
from LaserGRBLTests import EventRecorder, FileLoadingProbe

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus, fake_syncro, load_file_sync, wait_loaded

V = GrblCore.GrblVersionInfo
Q = GrblFile.CartesianQuadrant


def d(x):
    return float(str(x))


@pytest.fixture
def nc(tmp_path):
    def make(lines, name="f.nc"):
        p = tmp_path / name
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    return make


def loaded(path, append_to=None):
    f = append_to or GrblFile()
    load_file_sync(f, path, append_to is not None)
    return f


def rng(r):
    return (d(r.X.Min), d(r.Y.Min), d(r.X.Max), d(r.Y.Max))


def test_load_skips_blank_lines_and_keeps_comment_lines(nc):
    f = loaded(nc(["G0 X1", "", "   ", "; just a comment", "(another)", "g1 x2 f100"]))
    # comment-only lines are kept as commands, and the analysis pass (BuildHelper)
    # rewrites their text to "" -> they are later streamed as empty lines (F-17)
    assert [c.Command for c in f] == ["G0 X1", "", "", "G1 X2 F100"]
    assert f.Count == 4 and f[3].Command == "G1 X2 F100"
    assert len(list(f.Commands)) == 4


def test_load_missing_file_gives_empty_program(tmp_path):
    f = loaded(str(tmp_path / "missing.nc"))
    assert f.Count == 0 and f.EstimatedTime.TotalSeconds == 0


def test_append_keeps_previous_commands(nc):
    f = loaded(nc(["G0 X1"], "a.nc"))
    loaded(nc(["G0 X2"], "b.nc"), f)
    assert [c.Command for c in f] == ["G0 X1", "G0 X2"]
    loaded(nc(["G0 X3"], "c.nc"))  # a fresh file is independent
    assert f.Count == 2


def test_analysis_ranges_and_time(nc):
    GrblCore.Configuration = GrblConfST(V(1, 1), _dict({110: "6000", 111: "6000"}))
    f = loaded(nc(["G0 X10 Y10", "M3 S500", "G1 X20 Y10 F600", "G1 Y30 S1000", "M5", "G0 X-5 Y0"]))
    assert rng(f.Range.DrawingRange) == (10, 10, 20, 30)
    assert rng(f.Range.MovingRange) == (-5, 0, 20, 30)
    s = f.Range.SpindleRange
    assert (d(s.S.Min), d(s.S.Max), s.ValidRange) == (0, 1000, True)
    # G0 14.142 mm @6000 + 10 mm @600 + 20 mm @600 + G0 25 mm (to -5,0 from 20,30) @6000
    assert f.EstimatedTime.TotalSeconds == pytest.approx(0.141 + 1 + 2 + 0.391, abs=0.002)
    offsets = [c.TimeOffset.TotalSeconds for c in f]
    assert offsets == sorted(offsets) and offsets[-1] == pytest.approx(f.EstimatedTime.TotalSeconds)
    assert all(not c.JustBuilt for c in f)  # helpers are released after analysis


def test_analysis_arc_extends_range_with_its_bbox(nc):
    f = loaded(nc(["G0 X0 Y0", "M3 S100", "G2 X10 Y0 I5 J0 F100"]))
    assert rng(f.Range.DrawingRange) == (0, 0, 10, 5)


def test_analysis_bad_command_aborts_load(nc):
    GrblCore.Configuration = GrblConfST()
    f = GrblFile()
    path = nc(["G0 X1"])
    saved = cu.sget(Settings, "dic")
    # Analyze rethrows any exception (throw ex); with a null config table the G0
    # time computation throws, the loading thread logs it and the list stays filled
    cu.sset(Settings, "dic", None)
    try:
        f.LoadFile(path, False)
        wait_loaded(f)
    finally:
        cu.sset(Settings, "dic", saved)
    assert f.Count == 1


@pytest.mark.parametrize(
    "lines,quadrant",
    [
        (["M3 S1", "G1 X10 Y10 F1"], Q.I),
        (["G0 X-10 Y0", "M3 S1", "G1 X-1 Y10 F1"], Q.II),
        (["G0 X-10 Y-10", "M3 S1", "G1 X-1 Y-1 F1"], Q.III),
        (["G0 X1 Y-10", "M3 S1", "G1 X10 Y-1 F1"], Q.IV),
        (["G0 X-10 Y-10", "M3 S1", "G1 X10 Y10 F1"], Q.Mix),
        (["G0 X10 Y10"], Q.Unknown),
    ],
)
def test_quadrant(nc, lines, quadrant):
    assert loaded(nc(lines)).Quadrant == quadrant


def test_constructor_with_fake_range_and_clear():
    f = GrblFile(System.Decimal(0), System.Decimal(0), System.Decimal(300), System.Decimal(200))
    assert rng(f.Range.MovingRange) == (0, 0, 300, 200)
    assert not f.Range.DrawingRange.ValidRange
    f.Clear(System.Decimal(1), System.Decimal(2), System.Decimal(3), System.Decimal(4))
    wait_loaded(f)
    assert rng(f.Range.MovingRange) == (1, 2, 3, 4) and f.Count == 0


def test_check_in_use_without_message_box():
    f = GrblFile()
    assert not f.CheckInUse(False)
    cu.set(f, "InUse", True)
    assert f.CheckInUse(False)


def test_enumeration_both_interfaces(nc):
    f = loaded(nc(["G0 X1", "G0 X2"]))
    it = f.GetEnumerator()
    n = 0
    while it.MoveNext():
        n += 1
    assert n == 2
    git = cu.call(f, "System.Collections.Generic.IEnumerable<LaserGRBL.GrblCommand>.GetEnumerator")
    assert git.MoveNext() and git.Current.Command == "G0 X1"


def test_formatnumber():
    f = GrblFile()
    assert f.formatnumber(1.23456) == "1.235"
    assert f.formatnumber(2.0) == "2"


def _dict(dd):
    out = Dictionary[int, str]()
    for k, v in dd.items():
        out[k] = v
    return out


# ---------------------------------------------------------------- ranges
def test_xy_range_helpers():
    r = ProgramRange.XYRange()
    assert not r.ValidRange and (r.Center.X, r.Center.Y) == (0, 0)
    r.UpdateRange(GrblCommand.Element("X", System.Decimal(2)), None)
    assert not r.ValidRange
    r.UpdateRange(None, GrblCommand.Element("Y", System.Decimal(4)))
    r.UpdateRange(GrblCommand.Element("X", System.Decimal(6)), GrblCommand.Element("Y", System.Decimal(8)))
    assert r.ValidRange and d(r.Width) == 4 and d(r.Height) == 4
    assert (r.Center.X, r.Center.Y) == (4, 6)
    r.ResetRange()
    assert not r.ValidRange


def test_spindle_range_validity_rules():
    s = ProgramRange.SRange()
    assert not s.ValidRange
    s.UpdateRange(System.Decimal(0))
    assert not s.ValidRange  # min == max
    s.UpdateRange(System.Decimal(0))
    assert not s.ValidRange
    s2 = ProgramRange.SRange()
    s2.UpdateRange(System.Decimal(-5))
    s2.UpdateRange(System.Decimal(0))
    assert not s2.ValidRange  # max must be > 0
    s2.UpdateRange(System.Decimal(10))
    assert s2.ValidRange
    s2.ResetRange()
    assert not s2.ValidRange


def test_program_range_update_spindle_ignores_null():
    p = ProgramRange()
    p.UpdateSRange(None)
    assert not p.SpindleRange.S.ValidRange


# ---------------------------------------------------------------- save
def save(f, path, rig, header=True, footer=True, between=False, cycles=1, lf=True):
    f.SaveGCODE(str(path), header, footer, between, cycles, lf, rig.core)


def test_save_gcode_with_header_footer_and_passes(nc, tmp_path, rigs):
    rig = rigs()
    f = loaded(nc(["G0 X1", "G1 X2 F100"]))
    out = tmp_path / "out.nc"
    Settings.SetObject("GCode.CustomPasses", "G91\r\nG0 Z-1\r\n\r\nG90")
    save(f, out, rig, between=True, cycles=2)
    assert out.read_bytes().decode() == (
        "G90 (use absolute coordinates)\nG0 X1\nG1 X2 F100\nG91\nG0 Z-1\nG90\nG0 X1\nG1 X2 F100\n"
        "G0 X0 Y0 Z0 (move back to origin)\n")


def test_save_gcode_without_lf_option_uses_platform_newline(nc, tmp_path, rigs):
    rig = rigs()
    f = loaded(nc(["G0 X1"]))
    out = tmp_path / "out.nc"
    save(f, out, rig, header=False, footer=False, lf=False)
    # StreamWriter's default NewLine = Environment.NewLine: CRLF on Windows, LF here
    assert out.read_bytes() == b"G0 X1" + System.Environment.NewLine.encode()


def test_save_gcode_header_expressions_are_evaluated(nc, tmp_path, rigs):
    rig = rigs()
    Settings.SetObject("GCode.CustomHeader", "G0 X[left] Y[top]")
    f = loaded(nc(["G0 X5 Y5", "M3 S1", "G1 X9 Y7 F1"]))
    rig.core.LoadedFile  # noqa: B018 (the core's own file is used for the expressions)
    out = tmp_path / "out.nc"
    save(f, out, rig, footer=False)
    assert out.read_text().splitlines()[0] == "G0 X0.000 Y0.000"  # core's file is empty


def test_save_gcode_to_invalid_path_is_silent(nc, tmp_path, rigs):
    rig = rigs()
    f = loaded(nc(["G0 X1"]))
    save(f, tmp_path / "no" / "such" / "dir.nc", rig)
    assert not (tmp_path / "no").exists()


def test_save_gcode_skips_lines_that_evaluate_to_empty(nc, tmp_path, rigs):
    rig = rigs()
    Settings.SetObject("GCode.CustomFooter", "   \r\nM5")
    f = loaded(nc(["G0 X1"]))
    out = tmp_path / "o.nc"
    save(f, out, rig, header=False)
    assert out.read_text() == "G0 X1\nM5\n"


# ---------------------------------------------------------------- core <-> file
def test_core_reports_file_events_and_resets_projection(nc, rigs):
    rig = rigs()
    path = nc(["G0 X1"])
    load_file_sync(rig.core.LoadedFile, path)
    assert rig.events[-2:] == [f"loading:{path}", f"loaded:{path}"]
    assert rig.core.HasProgram


def test_core_events_without_subscribers(nc):
    bare = GrblCore(fake_syncro(), None, None)  # no EventRecorder attached
    load_file_sync(bare.LoadedFile, nc(["G0 X1"]))
    bare.AutoSizeDrawing()
    bare.ZoomInDrawing()
    bare.ZoomOutDrawing()
    bare.LoopCount = System.Decimal(2)
    cu.call(bare, "SetStatus", MacStatus.Idle)
    assert bare.HasProgram


def test_core_open_file_requires_free_file(nc, rigs):
    rig = rigs()
    cu.set(rig.core.LoadedFile, "InUse", True)
    assert not rig.core.CanLoadNewFile and not rig.core.CanReOpenFile and not rig.core.CanNewProject
    rig.core.OpenFile(nc(["G0 X1"]), False)  # ignored
    rig.core.ReOpenFile()
    rig.core.NewProject()
    assert rig.core.LoadedFile.Count == 0


def test_core_open_gcode_needs_wait_cursor_ui(nc, rigs):
    rig = rigs()
    path = nc(["G0 X1"])
    rig.core.OpenFile(path, False)
    # the remembered file is stored before dispatching on the extension...
    assert str(Settings.GetObject[System.String]("Core.LastOpenFile", None)) == path
    assert rig.core.CanReOpenFile
    # ...but Cursor.Current needs a display, the error is logged and nothing loads
    assert rig.core.LoadedFile.Count == 0


def test_core_save_program_and_project_need_a_program(rigs):
    rig = rigs()
    rig.core.SaveProgram(None, True, True, False, 1, True)
    rig.core.SaveProject(None)
    assert not rig.core.HasProgram


def test_core_drawing_events(rigs):
    rig = rigs()
    rig.core.AutoSizeDrawing()
    rig.core.ZoomInDrawing()
    rig.core.ZoomOutDrawing()
    assert rig.events == ["autosize", "zoomin", "zoomout"]


def test_core_ui_flags_and_misc(rigs):
    rig = rigs()
    c = rig.core
    assert c.UIShowGrblConfig and c.UIShowUnlockButtons and c.Type == Firmware.Grbl
    assert c.BufferSize == 127 and c.GrblBlock == -1 and c.GrblBuffer == -1
    assert c.ProgramTime.TotalSeconds == 0 and c.ProgramGlobalTime.TotalSeconds == 0
    assert c.ProjectedTime.TotalSeconds == 0
    assert c.ShowLaserOffMovements.Value and c.ShowExecutedCommands.Value
    assert not c.ShowPerformanceDiagnostic.Value and c.ShowBoundingBox.Value and c.CrossCursor.Value
    assert c.PreviewLineSize.Value == 1.0 and c.AutoSizeOnDrawing.Value
    assert GrblCore.GCodeExtensions.Contains(".nc") and GrblCore.ImageExtensions.Contains(".png")
    assert GrblCore.ProjectFileExtensions.Contains(".lps")
    assert c.HotKeys is not None and not c.SuspendHK
    assert cu.call(c, "ValidateConfig", 33, "1") is None


def test_reload_replaces_and_disposes_previous_commands(nc):
    f = loaded(nc(["G0 X1", "G0 X2"], "a.nc"))
    old = f[0]
    load_file_sync(f, nc(["G0 X3"], "b.nc"), False)
    assert [c.Command for c in f] == ["G0 X3"] and old.LinkedDisplayList is None


def test_check_in_use_with_message_box_needs_a_display():
    f = GrblFile()
    cu.set(f, "InUse", True)
    with pytest.raises(Exception):
        f.CheckInUse(True)


def test_quadrant_mix_when_negative_x_spans_y(nc):
    f = loaded(nc(["G0 X-10 Y-5", "M3 S1", "G1 X-1 Y5 F1"]))
    assert f.Quadrant == Q.Mix


def test_spindle_range_with_only_negative_values_is_invalid():
    s = ProgramRange.SRange()
    s.UpdateRange(System.Decimal(-5))
    s.UpdateRange(System.Decimal(-1))
    assert not s.ValidRange


def test_file_loading_event_is_only_raised_when_loaded_has_subscribers(nc, rigs):
    rig = rigs(events=False)
    probe = FileLoadingProbe(rig.core)
    load_file_sync(rig.core.LoadedFile, nc(["G0 X1"]))
    # RiseOnFileLoading tests OnFileLoaded for null (FINDINGS.md F-10)
    assert probe.Count == 0
    rig.recorder = EventRecorder(rig.core)  # now OnFileLoaded has a subscriber
    load_file_sync(rig.core.LoadedFile, nc(["G0 X2"], "b.nc"))
    assert probe.Count == 1


def test_program_end_without_subscribers(nc, rigs):
    rig = rigs(events=False)
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    rig.open_stepped(MacStatus.Idle)
    load_file_sync(rig.core.LoadedFile, nc(["G0 X1"]))
    rig.core.LoopCount = System.Decimal(2)
    rig.core.RunProgram(None)
    rig.pump()
    assert not rig.core.InProgram and rig.device.lines.count("G0X1") == 2
