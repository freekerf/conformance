"""Value types of GrblCore.cs: GrblVersionInfo, GPoint, GrblConfST, GrblConf (obsolete),
TimeProjection."""

import pytest

import System
from System.Collections.Generic import Dictionary
from System.Globalization import CultureInfo
from System.Threading import Thread
from LaserGRBL import GPoint, GrblConf, GrblConfST, GrblCore, GrblFile, Settings, TimeProjection
from Tools import HiResTimer

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import get_setting

V = GrblCore.GrblVersionInfo
Issue = GrblCore.DetectedIssue


def op(name, a, b, cls=V):
    return cu.scall(cls, name, a, b)


# ---------------------------------------------------------------- GrblVersionInfo
def test_version_to_string():
    assert str(V(1, 1, "f")) == "1.1f"
    assert str(V(0, 9)) == "0.9"


def test_version_equality_operators_with_nulls():
    assert op("op_Equality", None, None)
    assert not op("op_Equality", None, V(1, 1))
    assert not op("op_Equality", V(1, 1), None)
    assert op("op_Equality", V(1, 1, "f"), V(1, 1, "f"))
    assert op("op_Inequality", V(1, 1, "f"), V(1, 1, "h"))


def test_version_ordering():
    assert op("op_LessThan", V(1, 0), V(1, 1))
    assert op("op_LessThanOrEqual", V(1, 1), V(1, 1))
    assert op("op_GreaterThan", V(2, 0), V(1, 9))
    assert op("op_GreaterThanOrEqual", V(1, 1, "f"), V(1, 1))
    assert V(1, 1, "f").CompareTo(V(1, 1, "h")) == -1
    assert V(1, 1, "h").CompareTo(V(1, 1, "f")) == 1
    assert V(1, 2).CompareTo(V(1, 1)) == 1 and V(1, 1).CompareTo(V(1, 2)) == -1
    assert V(0, 9).CompareTo(V(1, 0)) == -1 and V(2, 0).CompareTo(V(1, 0)) == 1
    assert V(1, 1).CompareTo(V(1, 1)) == 0
    assert V(1, 1).CompareTo(None) == 1


def test_version_ordering_with_null_left_operand_throws():
    with pytest.raises(System.ArgumentNullException):
        op("op_LessThan", None, V(1, 1))
    with pytest.raises(System.ArgumentNullException):
        op("op_LessThanOrEqual", None, V(1, 1))
    with pytest.raises(System.ArgumentNullException):
        op("op_GreaterThan", V(1, 1), None)  # implemented as b < a


def test_version_compare_to_other_type_throws():
    with pytest.raises(System.ArgumentException):
        V(1, 1).CompareTo("1.1")


def test_version_equality_considers_ortur_and_hal_flags():
    assert not V(1, 1, "f", "Ortur Laser Master 2", None, False).Equals(V(1, 1, "f"))
    assert not V(1, 1, "f", None, None, True).Equals(V(1, 1, "f"))
    assert V(1, 1, "f", "Longer Nano", None, False).Equals(V(1, 1, "f"))  # Longer flag ignored
    assert not V(1, 1).Equals("1.1")
    a, b = V(1, 1, "f", "Ortur", "170", False), V(1, 1, "f", "Ortur", "170", False)
    assert a.GetHashCode() == b.GetHashCode()


def test_version_vendor_flags():
    ortur = V(1, 1, "f", "Ortur Laser Master 3", "182", False)
    assert ortur.IsOrtur and not ortur.IsLonger and ortur.IsLuckyWiFi
    assert ortur.MachineName == "Ortur Laser Master 3" and ortur.OrturFWVersionNumber == 182
    assert ortur.VendorName == "Ortur"
    assert V(1, 1, "f", "Aufero AL1", None, False).IsOrtur
    longer = V(1, 1, "f", "Longer Nano", None, False)
    assert longer.IsLonger and longer.IsLuckyWiFi
    assert V(1, 1, "f", "NanoDuo", None, False).IsLuckyWiFi
    assert not V(1, 1, "f", "Longer Ray5", None, False).IsLuckyWiFi
    assert not V(1, 1, "f", "Ortur Laser Master 2", None, False).IsLuckyWiFi
    assert V(1, 1, "f").OrturFWVersionNumber == -1
    assert V(1, 1, "f", None, None, True).IsHAL
    assert (V(1, 1).Major, V(1, 1).Minor) == (1, 1)


def test_version_vendor_name_vigotec_is_never_detected():
    # ToLower() is compared with "Vigotec" (capital V): never true (FINDINGS.md F-05)
    assert V(1, 1, "f", "Vigotec VG-L7X", None, False).VendorName == "Unknown"
    assert V(1, 1, "#").VendorName == "Emulator"
    assert V(1, 1, "f").VendorName == "Unknown"


def test_version_clone():
    a = V(1, 1, "f", "Ortur", "170", True)
    b = a.Clone()
    assert b.Equals(a) and not System.Object.ReferenceEquals(a, b)


# ---------------------------------------------------------------- GPoint
def test_gpoint_arithmetic_and_equality():
    a, b = GPoint(1, 2, 3), GPoint(0.5, 1, 1)
    s = op("op_Addition", a, b, GPoint)
    dif = op("op_Subtraction", a, b, GPoint)
    assert (s.X, s.Y, s.Z) == (1.5, 3, 4)
    assert (dif.X, dif.Y, dif.Z) == (0.5, 1, 2)
    assert op("op_Equality", a, GPoint(1, 2, 3), GPoint)
    assert op("op_Inequality", a, b, GPoint)
    assert a.Equals(GPoint(1, 2, 3)) and not a.Equals("p")
    assert a.GetHashCode() == GPoint(1, 2, 3).GetHashCode()
    z = GPoint.Zero
    assert (z.X, z.Y, z.Z) == (0, 0, 0)
    p = cu.call(a, "ToPointF")
    assert (p.X, p.Y) == (1, 2)


# ---------------------------------------------------------------- GrblConfST
def table(**kv):
    d = Dictionary[int, str]()
    for k, v in kv.items():
        d[int(k.lstrip("_"))] = str(v)
    return d


def test_conf_defaults_without_version():
    c = GrblConfST()
    assert c.GrblVersion is None and c.Count == 0
    assert c.ExpectedCount == 23
    assert c.HomingEnabled and c.LaserMode
    assert (float(str(c.MaxRateX)), float(str(c.MaxRateY))) == (4000, 4000)
    assert float(str(c.TableWidth)) == 300 and float(str(c.TableHeight)) == 200
    assert float(str(c.ResolutionX)) == 250 and float(str(c.ResolutionY)) == 250
    assert float(str(c.MinPWM)) == 0 and float(str(c.MaxPWM)) == 1000
    assert float(str(c.AccelerationXY)) == 2000 and not c.SoftLimit
    assert c.WiFi_SSID is None and c.WiFi_Pwd is None and c.TelnetPort == "23"


def test_conf_reads_v11_keys():
    c = GrblConfST(V(1, 1, "f"), table(_22=0, _32=1, _110=5000, _111=4500, _130=410, _131=400.5, _20=1,
                                        _30=255, _31=2, _100=80, _101=81, _120=100, _121=300, _74="ssid", _75="pw", _305="8023"))
    assert c.ExpectedCount == 34
    assert not c.HomingEnabled and c.LaserMode and c.SoftLimit
    assert float(str(c.MaxRateX)) == 5000 and float(str(c.MaxRateY)) == 4500
    assert float(str(c.TableWidth)) == 410 and float(str(c.TableHeight)) == 400.5
    assert float(str(c.MaxPWM)) == 255 and float(str(c.MinPWM)) == 2
    assert float(str(c.ResolutionX)) == 80 and float(str(c.ResolutionY)) == 81
    assert float(str(c.AccelerationXY)) == 200
    assert (c.WiFi_SSID, c.WiFi_Pwd, c.TelnetPort) == ("ssid", "pw", "8023")


def test_conf_v09_and_older_key_maps():
    c09 = GrblConfST(V(0, 9, "j"), table(_22=1, _32=1, _110=1234))
    assert c09.ExpectedCount == 31 and c09.HomingEnabled and not c09.LaserMode
    assert float(str(c09.MaxRateX)) == 1234
    c08 = GrblConfST(V(0, 8, "c"), table(_17=0, _4=777, _5=666, _0=99, _1=98))
    assert c08.ExpectedCount == 23 and not c08.HomingEnabled
    assert float(str(c08.MaxRateX)) == 777 and float(str(c08.MaxRateY)) == 666
    assert float(str(c08.ResolutionX)) == 99 and float(str(c08.ResolutionY)) == 98
    assert float(str(c08.TableWidth)) == 300  # no key before 0.9 -> default


def test_conf_values_are_clamped():
    c = GrblConfST(V(1, 1), table(_110=0, _130=99999999, _22=5))
    assert float(str(c.MaxRateX)) == 1  # min
    assert float(str(c.TableWidth)) == 2000000  # max
    assert c.HomingEnabled


def test_conf_unparseable_value_uses_regex_then_default():
    c = GrblConfST(V(1, 1), table(_110="500.5 mm/min", _111="none"))
    assert float(str(c.MaxRateX)) == 500.5
    assert float(str(c.MaxRateY)) == 4000


def test_conf_regex_fallback_parses_with_current_culture():
    c = GrblConfST(V(1, 1), table(_110="500.5 mm/min"))
    prev = Thread.CurrentThread.CurrentCulture
    Thread.CurrentThread.CurrentCulture = CultureInfo("it-IT")
    try:
        # "500.5" read with a comma-decimal culture: '.' is a group separator
        # -> 5005 (FINDINGS.md F-13)
        assert float(str(c.MaxRateX)) == 5005
    finally:
        Thread.CurrentThread.CurrentCulture = prev


def test_conf_add_or_update_and_foxalien_cleanup():
    c = GrblConfST(V(1, 1))
    c.AddOrUpdate("$110=500.000")
    c.AddOrUpdate("$110 = 600.000")
    c.AddOrUpdate("$20=1 (soft limits, bool)\r")
    c.AddOrUpdate("$74=My Net (home)")  # not numeric: Foxalien cleanup does not apply
    c.AddOrUpdate("ok")
    c.AddOrUpdate("$99999999999=1")  # int overflow, swallowed
    d = {kv.Key: kv.Value for kv in c}
    assert d == {110: "600.000", 20: "1", 74: "My Net (home)"}
    assert c.Count == 3


def test_conf_set_value_if_key_exist():
    c = GrblConfST(V(1, 1), table(_110=1))
    assert cu.call(c, "SetValueIfKeyExist", "$110=2")
    assert not cu.call(c, "SetValueIfKeyExist", "$111=2")
    assert not cu.call(c, "SetValueIfKeyExist", "G0 X1")
    assert not cu.call(c, "SetValueIfKeyExist", "$99999999999=1")
    assert {kv.Key: kv.Value for kv in c} == {110: "2"}


def test_conf_is_set_conf_regex():
    assert GrblConfST.IsSetConf("$0=10")
    assert GrblConfST.IsSetConf("$10 =abc")
    assert not GrblConfST.IsSetConf("$$")
    assert not GrblConfST.IsSetConf(" $1=1")


def test_conf_param_list_and_changes():
    c = GrblConfST(V(1, 1), table(_110=500, _0=10))
    params = {p.Number: p for p in c.ToList()}
    p = params[110]
    assert p.DollarNumber == "$110" and p.Value == "500"
    assert p.Parameter == "X-axis maximum rate" and p.Unit == "mm/min"
    assert p.Description.startswith("X-axis maximum rate")
    k = p.Clone()
    k.Value = "600"
    assert p.Value == "500"
    P = GrblConfST.GrblConfParam
    assert not cu.call(c, "HasChanges", P(110, "500"))
    assert cu.call(c, "HasChanges", P(110, "600"))
    assert cu.call(c, "HasChanges", P(111, "1"))
    it = cu.call(c, "System.Collections.IEnumerable.GetEnumerator")
    keys = []
    while it.MoveNext():
        keys.append(it.Current.Key)
    assert sorted(keys) == [0, 110]


def test_conf_validate_config_protects_ortur_safety_param():
    ortur = GrblConfST(V(1, 1, "f", "Ortur Laser Master 2", "170", False))
    assert "Ortur safety" in cu.call(ortur, "ValidateConfig", 33, "0")
    assert cu.call(ortur, "ValidateConfig", 32, "0") is None
    assert cu.call(GrblConfST(V(1, 1)), "ValidateConfig", 33, "0") is None
    assert cu.call(GrblConfST(), "ValidateConfig", 33, "0") is None


def test_conf_strings_without_version_return_defaults():
    c = GrblConfST(None, table(_74="x"))
    assert c.WiFi_SSID is None


# ---------------------------------------------------------------- GrblConf (obsolete format)
def dtable(**kv):
    d = Dictionary[int, System.Decimal]()
    for k, v in kv.items():
        d[int(k.lstrip("_"))] = System.Decimal(v)
    return d


def test_obsolete_conf_reads_values():
    c = GrblConf(V(1, 1, "f"), dtable(_22=0, _32=1, _110=5000, _111=4000, _130=400, _131=300, _20=1, _30=255,
                                     _31=1, _100=80, _101=80, _120=100, _121=200))
    assert c.ExpectedCount == 34 and not c.HomingEnabled and c.LaserMode and c.SoftLimit
    assert [float(str(x)) for x in (c.MaxRateX, c.MaxRateY, c.TableWidth, c.TableHeight, c.MaxPWM, c.MinPWM,
                                    c.ResolutionX, c.ResolutionY, c.AccelerationXY)] == [5000, 4000, 400, 300, 255, 1, 80, 80, 150]
    assert c.GrblVersion.Equals(V(1, 1, "f")) and c.Count == 13


def test_obsolete_conf_defaults_and_old_versions():
    c = GrblConf()
    assert c.ExpectedCount == 23 and c.HomingEnabled and c.LaserMode
    assert float(str(c.MaxRateX)) == 4000
    c9 = GrblConf(V(0, 9))
    assert c9.ExpectedCount == 31 and not c9.LaserMode and float(str(c9.TableWidth)) == 300
    c8 = GrblConf(V(0, 8), dtable(_17=0, _4=10))
    assert not c8.HomingEnabled and float(str(c8.MaxRateX)) == 10


def test_obsolete_conf_parsing_and_params():
    c = GrblConf(V(1, 1))
    c.AddOrUpdate("$110=500")
    c.AddOrUpdate("$110 = 600.5")
    c.AddOrUpdate("$74=abc")  # not numeric for the old format
    c.AddOrUpdate("$99999999999=1")
    assert {kv.Key: float(str(kv.Value)) for kv in c} == {110: 600.5}
    assert cu.call(c, "SetValueIfKeyExist", "$110=7")
    assert not cu.call(c, "SetValueIfKeyExist", "$111=7")
    assert not cu.call(c, "SetValueIfKeyExist", "x")
    assert not cu.call(c, "SetValueIfKeyExist", "$99999999999=1")
    assert GrblConf.IsSetConf("$1=2") and not GrblConf.IsSetConf("$1=a")
    p = c.ToList()[0]
    assert p.DollarNumber == "$110" and float(str(p.Value)) == 7
    assert p.Parameter == "X-axis maximum rate" and p.Unit == "mm/min" and p.Description.startswith("X-axis")
    p.Value = System.Decimal(8)
    assert float(str(p.Clone().Value)) == 8
    P = GrblConf.GrblConfParam
    assert not cu.call(c, "HasChanges", P(110, System.Decimal(7)))
    assert cu.call(c, "HasChanges", P(110, System.Decimal(9)))
    assert cu.call(c, "HasChanges", P(1, System.Decimal(9)))
    it = cu.call(c, "System.Collections.IEnumerable.GetEnumerator")
    assert it.MoveNext()
    ortur = GrblConf(V(1, 1, "f", "Ortur Laser Master 2", None, False))
    assert "Ortur" in cu.call(ortur, "ValidateConfig", 33, None)
    assert cu.call(c, "ValidateConfig", 33, None) is None


def test_conf_st_converts_from_obsolete_format():
    old = GrblConf(V(1, 1, "f"), dtable(_110=500.5, _22=1))
    new = GrblConfST(old)
    assert {kv.Key: kv.Value for kv in new} == {110: "500.5", 22: "1"}
    assert new.GrblVersion.Equals(V(1, 1, "f"))
    empty = cu.new(GrblConfST, None, types=[GrblConf])
    assert empty.Count == 0 and empty.GrblVersion is None


def test_core_configuration_migrates_obsolete_setting():
    old = GrblConf(V(1, 1, "f"), dtable(_110=1234))
    Settings.SetObject("Grbl Configuration", old)
    conf = GrblCore.Configuration
    assert float(str(conf.MaxRateX)) == 1234
    assert get_setting("Grbl Configuration") is None
    assert get_setting("Grbl Configuration ST") is not None


def test_core_configuration_setter_ignores_empty_config():
    GrblCore.Configuration = GrblConfST()
    assert get_setting("Grbl Configuration ST") is None
    GrblCore.Configuration = GrblConfST(V(1, 1), table(_110=1))
    assert GrblCore.Configuration.Count == 1


# ---------------------------------------------------------------- TimeProjection
def now():
    return HiResTimer.TotalMilliseconds


def fresh_file(seconds=100.0):
    f = GrblFile()
    cu.set(f, "mEstimatedTotalTime", System.TimeSpan.FromSeconds(seconds))
    return f


def queue(n):
    from LaserGRBL import GrblCommand

    q = System.Collections.Generic.Queue[GrblCommand]()
    for _ in range(n):
        q.Enqueue(GrblCommand("G0"))
    return q


def test_time_projection_initial_state():
    tp = TimeProjection()
    assert not tp.InProgram and tp.Target == 0 and tp.Sent == 0 and tp.Executed == 0
    assert tp.ProjectedTarget.TotalSeconds == 0 and tp.TotalJobTime.TotalSeconds == 0
    assert tp.TotalGlobalJobTime.TotalSeconds == 0 and tp.EstimatedTarget.TotalSeconds == 0
    assert tp.LastIssue == Issue.Unknown and tp.ErrorCount == 0


def test_time_projection_job_counters():
    tp = TimeProjection()
    tp.JobStart(fresh_file(100), queue(4), True)
    assert tp.InProgram and tp.Target == 4 and tp.EstimatedTarget.TotalSeconds == 100
    tp.JobStart(fresh_file(5), queue(1), True)  # ignored while started
    assert tp.Target == 4
    tp.JobSent()
    tp.JobSent()
    tp.JobExecuted(System.TimeSpan.FromSeconds(50))
    tp.JobError()
    assert (tp.Sent, tp.Executed, tp.ErrorCount) == (2, 1, 1)
    assert tp.ProjectedTarget.TotalSeconds >= 0
    assert tp.JobEnd(True)
    assert not tp.InProgram and not tp.JobEnd(True)
    tp.JobSent()
    tp.JobExecuted(System.TimeSpan.Zero)
    tp.JobError()
    assert (tp.Sent, tp.Executed, tp.ErrorCount) == (2, 1, 1)  # frozen after the end


def test_time_projection_projects_from_progress():
    tp = TimeProjection()
    tp.JobStart(fresh_file(100), queue(1), True)
    cu.set(tp, "mStart", System.Int64(now() - 10000))  # 10 s of job time
    tp.JobExecuted(System.TimeSpan.FromSeconds(25))  # 25% of the estimate done
    assert tp.ProjectedTarget.TotalSeconds == pytest.approx(40, abs=0.5)
    assert tp.TotalJobTime.TotalSeconds == pytest.approx(10, abs=0.5)


def test_time_projection_without_progress_returns_estimate():
    tp = TimeProjection()
    tp.JobStart(fresh_file(100), queue(1), True)
    assert tp.ProjectedTarget.TotalSeconds == 100


def test_time_projection_pauses_are_excluded_from_true_time():
    tp = TimeProjection()
    tp.JobStart(fresh_file(100), queue(1), True)
    cu.set(tp, "mStart", System.Int64(now() - 10000))
    tp.JobPause()
    tp.JobPause()  # idempotent
    cu.set(tp, "mPauseBegin", System.Int64(now() - 4000))
    tp.JobExecuted(System.TimeSpan.FromSeconds(30))
    # real job time 10 s minus 4 s paused = 6 s for 30% -> 20 s + 4 s of pause
    assert tp.ProjectedTarget.TotalSeconds == pytest.approx(24, abs=0.5)
    tp.JobResume()
    tp.JobResume()  # no-op when not paused
    assert cu.get(tp, "mCumulatedPause") >= 4000
    tp.JobEnd(False)
    # a non-global end does not record mGlobalEnd: the global time is then
    # (0 - globalStart), i.e. negative, until the next pass starts (FINDINGS.md F-14)
    assert tp.TotalGlobalJobTime.TotalSeconds < 0


def test_time_projection_global_time_spans_passes():
    tp = TimeProjection()
    tp.JobStart(fresh_file(), queue(1), True)
    cu.set(tp, "mGlobalStart", System.Int64(now() - 5000))
    assert tp.TotalGlobalJobTime.TotalSeconds == pytest.approx(5, abs=0.5)
    tp.JobEnd(True)
    assert tp.TotalGlobalJobTime.TotalSeconds == pytest.approx(5, abs=0.5)
    assert tp.TotalJobTime.TotalSeconds >= 0
    tp.Reset(False)
    assert cu.get(tp, "mGlobalStart") != 0  # non-global reset keeps the global start


def test_time_projection_continue_from_position():
    tp = TimeProjection()
    tp.JobContinue(fresh_file(60), 10, 3)
    assert tp.InProgram and tp.EstimatedTarget.TotalSeconds == 60
    assert tp.Target == 0  # file.Count of an empty file
    assert (tp.Sent, tp.Executed) == (7, 7)  # position minus the 3 injected commands
    tp.JobContinue(fresh_file(1), 99, 0)  # ignored while started
    assert tp.Sent == 7
    tp.JobEnd(True)
    tp.JobContinue(fresh_file(1), 2, 0)  # keeps the previous estimate and start time
    assert tp.EstimatedTarget.TotalSeconds == 60


def test_time_projection_last_known_wco_only_while_in_program():
    tp = TimeProjection()
    tp.LastKnownWCO = GPoint(1, 2, 3)
    assert tp.LastKnownWCO.X == 0
    tp.JobStart(fresh_file(), queue(1), True)
    tp.LastKnownWCO = GPoint(1, 2, 3)
    assert tp.LastKnownWCO.X == 1
    tp.JobIssue(Issue.MachineAlarm)
    assert tp.LastIssue == Issue.MachineAlarm
