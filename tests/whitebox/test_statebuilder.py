"""StatePositionBuilder / StateBuilder / G2G3Helper: the G-code interpreter used for
time estimation, bounding boxes, the emulator and job resume."""

import math

import pytest

import System
from System.Collections.Generic import Dictionary
from LaserGRBL import GrblCommand, GrblConfST, GrblCore, JogCommand, ProgramRange, Settings

from lasergrbl_harness import clr_util as cu

SPB = GrblCommand.StatePositionBuilder
G2G3 = GrblCommand.G2G3Helper


def conf(**values):
    d = Dictionary[int, str]()
    for k, v in values.items():
        d[int(k.lstrip("_"))] = str(v)
    return GrblConfST(GrblCore.GrblVersionInfo(1, 1, "f"), d)


CONF = conf(_110=6000, _111=6000)  # max rate 6000 mm/min


def run(lines, spb=None, c=CONF):
    spb = spb or SPB()
    total = 0.0
    for ln in lines:
        cmd = ln if not isinstance(ln, str) else GrblCommand(ln)
        total += spb.AnalyzeCommand(cmd, True, c).TotalSeconds
    return spb, total


def d(x):
    return float(str(x))


def pos(spb):
    return d(spb.X.Number), d(spb.Y.Number), d(spb.Z.Number)


# ---------------------------------------------------------------- position tracking
def test_absolute_moves_update_position():
    spb, _ = run(["G0 X10 Y5", "G1 Z-1 F100"])
    assert pos(spb) == (10, 5, -1)
    assert spb.X.IsSettled and spb.Z.IsSettled
    assert not spb.X.IsDefault


def test_relative_moves_accumulate():
    spb, _ = run(["G91", "G0 X10", "X5 Y-2"])
    assert pos(spb)[:2] == (15, -2)
    assert d(spb.X.Previous) == 10


def test_default_state_before_any_move():
    spb = SPB()
    assert spb.X.IsDefault and not spb.X.IsSettled
    assert spb.F.IsDefault and not spb.F.IsSettled
    assert spb.ABS and spb.G0 and spb.G0G1 and not spb.G2G3 and not spb.HasWCO


def test_feed_and_power_are_last_value():
    spb, _ = run(["G1 X1 F100 S10", "X2", "S20"])
    assert d(spb.F.Number) == 100 and d(spb.S.Number) == 20
    assert spb.S.IsSettled and not spb.S.IsDefault


def test_g92_sets_work_offset_and_offsets_later_absolute_moves():
    spb, _ = run(["G0 X10 Y10 Z1", "G92 X5 Y0", "G0 X1 Y1"])
    assert spb.HasWCO
    assert (d(spb.WcoX), d(spb.WcoY), d(spb.WcoZ)) == (5, 10, 0)
    assert pos(spb)[:2] == (6, 11)


def test_g92_z_only():
    spb, _ = run(["G0 Z3", "G92 Z1"])
    assert d(spb.WcoZ) == 2 and spb.HasWCO


def test_non_movement_commands_do_not_move():
    spb, _ = run(["G0 X3", "M3 S100", "G4 P1"])
    assert pos(spb)[0] == 3


def test_jog_command_uses_its_own_distance_mode_and_ignores_modals():
    spb, _ = run(["G0 X10", JogCommand("$J=G91X5Y1F600")])
    assert pos(spb)[:2] == (15, 1)
    assert spb.ABS  # jog does not change the modal distance mode
    spb2, _ = run(["G0 X10", JogCommand("$J=G90X2F600")])
    assert pos(spb2)[0] == 2
    assert d(spb2.F.Number) == 0  # jog feed is not remembered


def test_jog_command_strips_dollar_j_prefix():
    j = JogCommand("$J=G91 X1")
    assert j.Command == "G91 X1"


def test_homing_resets_position():
    spb, _ = run(["G0 X10 Y3"])
    cu.call(spb, "Homing")
    assert pos(spb) == (0, 0, 0) and spb.X.IsDefault


def test_true_movement():
    spb, _ = run(["G0 X1"])
    assert cu.call(spb, "TrueMovement")
    run(["G0 Z5"], spb)
    assert not cu.call(spb, "TrueMovement")
    run(["G2 X1 Y0 I0 J1"], spb)  # end == start but arc mode
    assert cu.call(spb, "TrueMovement")


# ---------------------------------------------------------------- modal groups
def test_modal_groups_track_only_their_own_codes():
    spb, _ = run(["G1 G91", "G55", "G18", "G93", "G20", "G43.1", "M8", "M4", "M30", "G91.1", "G40"])
    # duplicate G in one line keeps only the first (see test_grblcommand)
    assert d(spb.MotionMode.Number) == 1
    names = [str(e) for e in spb.GetSettledModals()]
    assert names == ["G55", "G18", "G91.1", "G93", "G40", "G43.1", "M30", "M8", "M4"]


def test_settled_modals_empty_by_default_and_motion_mode_excluded():
    spb, _ = run(["G1 X1"])
    assert list(spb.GetSettledModals()) == []
    assert d(spb.MotionMode.Number) == 1 and spb.MotionMode.IsSettled and not spb.MotionMode.IsDefault


def test_modal_element_ignores_unknown_values():
    spb, _ = run(["G38.2 X1", "G80"])
    assert str(spb.MotionMode) == "G80"
    spb2, _ = run(["G28"])
    assert str(spb2.MotionMode) == "G0" and spb2.MotionMode.IsDefault


def test_distance_mode_property():
    spb, _ = run(["G91"])
    assert not spb.ABS
    run(["G90"], spb)
    assert spb.ABS


# ---------------------------------------------------------------- execution time
def test_g0_time_uses_max_rate_x():
    _, t = run(["G0 X100"])  # 100 mm at 6000 mm/min
    assert t == pytest.approx(1.0)


def test_g1_time_uses_feed_capped_by_max_rate():
    _, t = run(["G1 X100 F600"])
    assert t == pytest.approx(10.0)
    _, t2 = run(["G1 X100 F60000"])
    assert t2 == pytest.approx(1.0)


def test_g1_without_feed_takes_no_time():
    _, t = run(["G1 X100"])
    assert t == 0


def test_dwell_time_from_p_or_s():
    assert run(["G4 P2.5"])[1] == pytest.approx(2.5)
    assert run(["G4 S3"])[1] == pytest.approx(3)
    assert run(["G4"])[1] == 0


def test_diagonal_segment_length():
    _, t = run(["G0 X30 Y40"])  # 50 mm
    assert t == pytest.approx(0.5)


def test_arc_time_uses_arc_length():
    spb, t = run(["G1 F600", "G2 X10 Y0 I5 J0"])
    # .NET Framework's TimeSpan.FromMinutes/FromSeconds round to whole milliseconds,
    # so every per-command estimate is quantized to 1 ms (relevant for a port)
    assert t == round(5 * math.pi / 600 * 60, 3) == 1.571
    assert spb.LastArcHelperResult is not None


def test_time_estimates_are_rounded_to_milliseconds():
    _, t = run(["G1 X1 F7"])  # 8.5714... s
    assert t == 8.571


def test_compute_false_returns_zero_and_keeps_helper_state():
    spb = SPB()
    c = GrblCommand("G0 X100")
    c.BuildHelper()
    assert spb.AnalyzeCommand(c, False, None).TotalSeconds == 0
    assert c.JustBuilt  # caller-built helper is not deleted
    c2 = GrblCommand("G0 X1")
    spb.AnalyzeCommand(c2, False, None)
    assert not c2.JustBuilt  # helper built by AnalyzeCommand is deleted


def test_jog_time_uses_g0_rate_because_jog_does_not_set_motion_mode():
    _, t = run([JogCommand("$J=G91X100F600")])
    assert t == pytest.approx(1.0)  # 100 mm at max rate, the jog F600 is ignored
    _, t2 = run(["G1 F1", JogCommand("$J=G91X100F600")])
    assert t2 == pytest.approx(10.0)  # in G1 mode the jog's own F is used


def test_default_config_max_rate():
    _, t = run(["G0 X4000"], c=GrblConfST())
    assert t == pytest.approx(60.0)  # default MaxRateX = 4000


# ---------------------------------------------------------------- laser state
def test_laser_burning_rules():
    spb, _ = run(["M3 S100"])
    assert spb.LaserBurning and spb.M3M4
    spb, _ = run(["M3 S0"])
    assert not spb.LaserBurning
    spb, _ = run(["M4 S100", "G0 X1"])
    assert not spb.LaserBurning  # dynamic mode does not burn on G0
    run(["G1 X2"], spb)
    assert spb.LaserBurning
    spb, _ = run(["M5 S100"])
    assert not spb.LaserBurning and not spb.M3M4


def test_laser_burning_without_hardware_pwm_ignores_power():
    Settings.SetObject("Support Hardware PWM", False)
    spb, _ = run(["M3 S0"])
    assert spb.LaserBurning


def _srange(lo, hi):
    r = ProgramRange.SRange()
    r.UpdateRange(System.Decimal(lo))
    r.UpdateRange(System.Decimal(hi))
    return r


def test_current_alpha():
    spb, _ = run(["G1 X1"])
    assert cu.call(spb, "GetCurrentAlpha", _srange(0, 1000)) == 150  # not burning
    run(["M3 S500"], spb)
    assert cu.call(spb, "GetCurrentAlpha", _srange(0, 1000)) == 127
    assert cu.call(spb, "GetCurrentAlpha", _srange(500, 500)) == 255  # invalid range
    Settings.SetObject("Support Hardware PWM", False)
    nopwm, _ = run(["M3 S500"])
    assert cu.call(nopwm, "GetCurrentAlpha", _srange(0, 1000)) == 255


# ---------------------------------------------------------------- arcs
def arc(start, line):
    spb, _ = run([f"G0 X{start[0]} Y{start[1]}", line])
    return spb.LastArcHelperResult or cu.call(spb, "GetArcHelper", GrblCommand(line))


def rect(r):
    return (round(r.X, 9), round(r.Y, 9), round(r.Width, 9), round(r.Height, 9))


def test_cw_half_circle_bbox_and_length():
    a = arc((0, 0), "G2 X10 Y0 I5 J0")
    assert (a.CenterX, a.CenterY, a.Ray) == (5, 0, 5)
    assert a.CW and a.AbsLenght == pytest.approx(5 * math.pi)
    assert a.Lenght == pytest.approx(-5 * math.pi)
    assert rect(a.BBox) == (0, 0, 10, 5)


def test_ccw_half_circle_bbox():
    a = arc((0, 0), "G3 X10 Y0 I5 J0")
    assert not a.CW
    assert rect(a.BBox) == (0, -5, 10, 5)
    assert a.Lenght == pytest.approx(5 * math.pi)


def test_full_circle_bbox_is_the_whole_circle():
    a = arc((0, 0), "G2 X0 Y0 I5 J0")
    assert rect(a.BBox) == (0, -5, 10, 10)
    assert (a.RectX, a.RectY, a.RectW, a.RectH) == (0, -5, 10, 10)


def test_quarter_arcs_in_every_quadrant():
    # CCW quarter arcs around (0,0) radius 1, starting in each quadrant
    cases = [
        ((1, 0), "G3 X0 Y1 I-1 J0", (0, 0, 1, 1)),
        ((0, 1), "G3 X-1 Y0 I0 J-1", (-1, 0, 1, 1)),
        ((-1, 0), "G3 X0 Y-1 I1 J0", (-1, -1, 1, 1)),
        ((0, -1), "G3 X1 Y0 I0 J1", (0, -1, 1, 1)),
    ]
    for start, line, box in cases:
        assert rect(arc(start, line).BBox) == box, line


def test_oblique_arc_angles_cover_all_atan_quadrants():
    # start points off the axes, so CalculateAngle takes its atan branches
    for start, line in [((1, 1), "G3 X-1 Y1 I-1 J-1"), ((-1, 1), "G3 X-1 Y-1 I1 J-1"),
                        ((-1, -1), "G3 X1 Y-1 I1 J1"), ((1, -1), "G3 X1 Y1 I-1 J1")]:
        a = arc(start, line)
        assert a.Ray == pytest.approx(math.sqrt(2))
        assert abs(a.AngularWidth) == pytest.approx(math.pi / 2)


def test_r_arc_assumes_center_at_chord_midpoint():
    a = arc((0, 0), "G2 X6 Y0 R5")
    # the R value is ignored: the center is always the midpoint of the chord
    # (correct only for half circles; see FINDINGS.md F-12)
    assert (a.CenterX, a.CenterY, a.Ray) == (3, 0, 3)


def test_arc_with_only_i_or_only_j():
    assert arc((0, 0), "G2 X10 Y0 I5").CenterX == 5
    assert arc((0, 0), "G2 X0 Y10 J5").CenterY == 5


@pytest.mark.parametrize("angle,quad", [(0, 1), (math.pi / 2, 2), (math.pi, 3), (3 * math.pi / 2, 4), (-0.1, 4), (2 * math.pi + 0.1, 1)])
def test_get_quadrant(angle, quad):
    assert G2G3.GetQuadrant(angle) == quad


def test_arc_helper_builds_helper_when_needed():
    spb, _ = run(["G0 X0 Y0", "G2 X10 Y0 I5 J0"])
    c = GrblCommand("G2 X10 Y0 I5 J0")
    h = G2G3(spb, c)
    assert not c.JustBuilt and h.Ray == 5


def test_arc_with_zero_offset_has_zero_radius():
    a = arc((0, 0), "G2 X10 Y0 I0 J0")  # center == start point
    assert a.Ray == 0 and a.StartAngle == 0


def test_wco_y_only_and_y_only_true_movement():
    spb, _ = run(["G0 Y3", "G92 Y1"])
    assert spb.HasWCO and d(spb.WcoY) == 2
    run(["G0 Y5"], spb)
    assert cu.call(spb, "TrueMovement")


def test_jog_without_feed_uses_modal_feed():
    _, t = run(["G1 F600", JogCommand("$J=G91X10")])
    assert t == pytest.approx(1.0)  # 10 mm at the modal F600


def test_g0g1_flag():
    spb, _ = run(["G1"])
    assert spb.G0G1 and not spb.G0
    run(["G2"], spb)
    assert not spb.G0G1 and spb.G2
