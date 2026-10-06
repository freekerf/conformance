"""Jogging: classic (G91/G1) for Grbl < 1.1, $J= for 1.1, and continuous jog."""

import pytest

import System
from System.Drawing import PointF
from System.Globalization import CultureInfo
from System.Threading import Thread
from LaserGRBL import GrblCommand, GrblConfST, GrblCore, Settings

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus

V = GrblCore.GrblVersionInfo
D = GrblCore.JogDirection
CJ = GrblCore.ContinuousJog


def conf(**kv):
    d = System.Collections.Generic.Dictionary[int, str]()
    for k, v in kv.items():
        d[int(k.lstrip("_"))] = str(v)
    return GrblConfST(V(1, 1), d)


@pytest.fixture
def v11(rigs):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    rig.open_stepped(MacStatus.Idle)
    rig.core.JogSpeed = 1000
    rig.core.JogStep = System.Decimal(10)
    return rig


@pytest.fixture
def v09(rigs):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(0, 9, "j"))
    rig.open_stepped(MacStatus.Idle)
    rig.core.JogSpeed = 500
    rig.core.JogStep = System.Decimal(1)
    return rig


def jog_to(rig, x, y, fast=False):
    # explicit overload: pythonnet would otherwise bind False to the float-speed overload
    rig.core.JogToPosition.Overloads[PointF, System.Boolean](PointF(x, y), fast)


def continuous(on=True):
    Settings.SetObject("Enable Continuous Jog", on)


# ---------------------------------------------------------------- Grbl 1.1 ($J=)
@pytest.mark.parametrize(
    "direction,expected",
    [
        (D.N, "$J=G91Y10.0F1000"), (D.S, "$J=G91Y-10.0F1000"), (D.E, "$J=G91X10.0F1000"),
        (D.W, "$J=G91X-10.0F1000"), (D.NE, "$J=G91X10.0Y10.0F1000"), (D.NW, "$J=G91X-10.0Y10.0F1000"),
        (D.SE, "$J=G91X10.0Y-10.0F1000"), (D.SW, "$J=G91X-10.0Y-10.0F1000"),
        (D.Zup, "$J=G91Z10.0F1000"), (D.Zdown, "$J=G91Z-10.0F1000"), (D.Home, "$J=G90X0Y0F1000"),
    ],
)
def test_jog_direction_v11(v11, direction, expected):
    v11.core.JogToDirection(direction, False)
    assert v11.queue_texts() == [expected]


def test_jog_fast_uses_100000_speed(v11):
    v11.core.JogToDirection(D.E, True)
    assert v11.queue_texts() == ["$J=G91X10.0F100000"]


def test_jog_step_is_rounded_to_one_decimal(v11):
    v11.core.JogToDirection(D.E, 1000.0, System.Decimal(0.25))
    v11.core.JogToDirection(D.E, 1000.0, System.Decimal(0.04))
    # "0.0" format: 0.25 -> 0.3 and 0.04 -> 0.0 (FINDINGS.md F-22)
    assert v11.queue_texts() == ["$J=G91X0.3F1000", "$J=G91X0.0F1000"]


def test_jog_feed_uses_current_culture(v11):
    prev = Thread.CurrentThread.CurrentCulture
    Thread.CurrentThread.CurrentCulture = CultureInfo("it-IT")
    try:
        v11.core.JogToDirection(D.E, 1234.5, System.Decimal(1))
    finally:
        Thread.CurrentThread.CurrentCulture = prev
    # the step is formatted invariantly, the float speed is not (FINDINGS.md F-21)
    assert v11.queue_texts() == ["$J=G91X1.0F1234,5"]


def test_jog_to_position_v11(v11):
    jog_to(v11, 12.345, 6.7)
    jog_to(v11, 1, 2, True)
    assert v11.queue_texts() == ["$J=G90X12.35Y6.70F1000", "$J=G90X1.00Y2.00F100000"]


def test_jog_to_position_clamped_by_soft_limits(v11):
    GrblCore.Configuration = conf(_20=1, _130=300, _131=200)
    v11.rx("<Idle|MPos:0,0,0|WCO:10,20,0>")
    jog_to(v11, 500, -50)
    assert v11.queue_texts() == ["$J=G90X290.00Y-20.00F1000"]


def test_jog_invalid_directions_throw(v11):
    for d in (D.Abort, D.Position):
        with pytest.raises(System.ArgumentException):
            v11.core.JogToDirection(d, False)
        with pytest.raises(System.ArgumentException):
            v11.core.ContinuousJogToDirection(d, 1000.0)


def test_jog_ignored_when_not_enabled(v11):
    v11.set_status(MacStatus.Run)
    assert not v11.core.JogEnabled
    v11.core.JogToDirection(D.E, False)
    jog_to(v11, 1, 1)
    v11.core.ContinuousJogToPosition(PointF(1, 1), 1.0)
    v11.core.ContinuousJogToDirection(D.E, 1.0)
    assert v11.queue.Count == 0
    v11.set_status(MacStatus.Jog)
    assert v11.core.JogEnabled


# ---------------------------------------------------------------- Grbl 0.9 (G-code emulation)
def test_jog_direction_v09_wraps_in_relative_mode(v09):
    v09.core.JogToDirection(D.NE, False)
    v09.core.JogToDirection(D.Zdown, False)
    v09.core.JogToDirection(D.Zup, False)
    v09.core.JogToDirection(D.SW, False)
    assert v09.queue_texts() == ["G91", "G1X1.0Y1.0F500", "G90", "G91", "G1Z-1.0F500", "G90",
                                 "G91", "G1Z1.0F500", "G90", "G91", "G1X-1.0Y-1.0F500", "G90"]


def test_jog_home_v09(v09):
    v09.core.JogToDirection(D.Home, False)
    assert v09.queue_texts() == ["G90", "G1X0Y0F500"]


def test_jog_to_position_v09(v09):
    jog_to(v09, 3, 4)
    assert v09.queue_texts() == ["G90", "G1X3.00Y4.00F500"]


def test_jog_enabled_rules_v09(v09):
    v09.set_status(MacStatus.Run)
    assert v09.core.JogEnabled  # old firmware: Run is ok when not in a program
    v09.set_status(MacStatus.Jog)
    assert not v09.core.JogEnabled


def test_continuous_jog_not_supported_v09(v09):
    continuous()
    v09.core.ContinuousJogToPosition(PointF(1, 1), 100.0)
    v09.core.ContinuousJogToDirection(D.E, 100.0)
    v09.core.ContinuousJogAbort()
    v09.core.JogAbort()
    assert cu.sget(CJ, "mCurr") is None and v09.queue.Count == 0


# ---------------------------------------------------------------- continuous jog
def test_continuous_jog_direction_is_sent_by_tx_loop(v11):
    continuous()
    GrblCore.Configuration = conf(_130=400, _131=300)
    v11.core.JogToDirection(D.NE, False)
    assert v11.queue.Count == 0  # only a target is set
    v11.step_tx()
    v11.link.pump()
    assert v11.device.lines == ["$J=G53X400.0Y300.0F1000"]


@pytest.mark.parametrize("d,expected", [(D.N, "$J=G53Y300.0F7"), (D.S, "$J=G53Y0.0F7"), (D.E, "$J=G53X400.0F7"),
                                        (D.W, "$J=G53X0.0F7"), (D.SW, "$J=G53X0.0Y0.0F7"), (D.NW, "$J=G53X0.0Y300.0F7"),
                                        (D.SE, "$J=G53X400.0Y0.0F7"), (D.Home, "$J=G90X0Y0F7")])
def test_continuous_jog_targets(v11, d, expected):
    GrblCore.Configuration = conf(_130=400, _131=300)
    v11.core.ContinuousJogToDirection(d, 7.0)
    v11.step_tx()
    v11.link.pump()
    assert v11.device.lines == [expected]


def test_continuous_jog_z_is_sent_as_step_jog(v11):
    continuous()
    v11.core.JogToDirection(D.Zup, False)
    assert v11.queue_texts() == ["$J=G91Z10.0F1000"]


def test_continuous_jog_new_target_aborts_previous(v11):
    continuous()
    v11.core.ContinuousJogToPosition(PointF(5, 6), 300.0)
    v11.step_tx()
    v11.deliver()
    jog_to(v11, 7, 8)
    v11.step_tx()
    v11.link.pump()
    assert v11.device.lines == ["$J=G90X5.00Y6.00F300", "$J=G90X7.00Y8.00F1000"]
    assert v11.device.realtime == [0x85]


def test_continuous_jog_abort_sends_jog_cancel_once(v11):
    continuous()
    v11.core.ContinuousJogToDirection(D.E, 100.0)
    v11.step_tx()
    v11.deliver()
    v11.core.JogAbort()
    v11.step_tx()
    v11.core.ContinuousJogAbort()
    v11.step_tx()  # previous command was already an abort: nothing to cancel
    v11.link.pump()
    assert v11.device.realtime == [0x85]


def test_jog_abort_without_continuous_jog_does_nothing(v11):
    v11.core.JogAbort()
    assert cu.sget(CJ, "mCurr") is None


def test_continuous_jog_waits_for_pending_commands(v11):
    v11.device.auto_ack = False
    v11.core.EnqueueCommand(GrblCommand("G0 X1"))
    v11.send_line()
    v11.core.ContinuousJogToDirection(D.E, 100.0)
    v11.step_tx()
    v11.link.pump()
    assert v11.device.lines == ["G0X1"]


def test_continuous_jog_static_api(v11):
    with pytest.raises(System.ArgumentException):
        CJ.ToDirection(D.Abort, 1.0)
    with pytest.raises(System.ArgumentException):
        CJ.ToDirection(D.Position, 1.0)
    with pytest.raises(System.ArgumentException):
        CJ.ToDirection(D.Zup, 1.0)
    with pytest.raises(System.ArgumentException):
        CJ.ToDirection(D.Zdown, 1.0)
    CJ.ToDirection(D.W, 5.0)
    target, abort = CJ.GetAndClearTarget(False)
    assert target.Direction == D.W and target.Speed == 5.0 and not abort
    again, _ = CJ.GetAndClearTarget(False)
    assert again is None  # same target is returned only once
    CJ.ToPosition(PointF(1, 2), 3.0)
    t2, abort2 = CJ.GetAndClearTarget(False)
    assert abort2 and t2.Target.X == 1
    CJ.Abort()
    t3, abort3 = CJ.GetAndClearTarget(False)
    assert t3.Direction == D.Abort and abort3
    CJ.Abort()
    t4, abort4 = CJ.GetAndClearTarget(False)
    assert t4.Direction == D.Abort and not abort4
