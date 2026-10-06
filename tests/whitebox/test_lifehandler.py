"""LaserLifeHandler (GrblCore.cs): laser-module usage counters, persistence and the
(opt-in) statistics upload. No real network: UrlManager URLs are null in this build;
the upload path is exercised against a local HTTP endpoint run in a subprocess."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import System
from System.Collections.Generic import Dictionary
import LaserGRBL
from LaserGRBL import GrblConfST, GrblCore, Settings, UrlManager
from Tools import HiResTimer

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import get_setting

LLH = getattr(LaserGRBL, "LaserLifeHandler")
LLC = LLH.LaserLifeCounter
MS = GrblCore.MacStatus
SUB = Path(__file__).parent / "subproc"


@pytest.fixture(autouse=True)
def isolated_counters():
    saved_list = cu.sget(LLH, "mLLCL")
    saved_cur = cu.sget(LLH, "mCurrentLLC")
    lst = LLH.ListLLC()
    lst.Add(LLC.CreateDefault())
    lst.LastAttempt = System.DateTime.Now  # never try to upload during the tests
    lst.LastSent = System.DateTime.Now
    cu.sset(LLH, "mLLCL", lst)
    cu.sset(LLH, "mCurrentLLC", None)
    cu.sset(LLH, "mLastStatusHiResTimeNano", None)
    cu.sset(LLH, "mLastPowerHiResTimeNano", None)
    yield lst
    cu.sset(LLH, "mLLCL", saved_list)
    cu.sset(LLH, "mCurrentLLC", saved_cur)
    UrlManager.LaserStatistics = None


def nano():
    return HiResTimer.TotalNano


def counters():
    return cu.sget(LLH, "mLLCL")


def hours(ts):
    return ts.TotalHours


# ---------------------------------------------------------------- LaserLifeCounter
def test_counter_defaults_and_properties():
    c = LLC.CreateDefault()
    assert c.Name == "Default" and len(c.Guid) == 36
    assert c.MonitoringDate == System.DateTime.Today  # Nullable<DateTime> unwrapped by pythonnet
    assert c.TimeInRun.TotalSeconds == 0 and c.AveragePowerFactor == 0 and len(c.Classes) == 10
    assert not cu.call(c, "HasWorked")
    n = cu.scall(LLC, "CreateNew")
    assert n.Name is None
    c.Brand, c.Model = "B", "M"
    c.OpticalPower = 5.5
    c.PurchaseDate = System.DateTime(2020, 1, 2)
    c.DeathDate = None
    c.LastUsage = None
    assert (c.Brand, c.Model, c.OpticalPower) == ("B", "M", 5.5)


def test_counter_true_time_classes_and_thresholds():
    c = LLC.CreateDefault()
    one_h = System.TimeSpan.FromHours(1)
    cu.call(c, "AddTrueLaserTimePower", one_h, 0.02)  # < 3%: not in power stats, class 0
    assert c.AveragePowerFactor == 0 and hours(c.Classes[0]) == 1
    cu.call(c, "AddTrueLaserTimePower", one_h, 0.005)  # < 1%: ignored entirely
    assert hours(c.Classes[0]) == 1
    cu.call(c, "AddTrueLaserTimePower", one_h, 0.5)
    cu.call(c, "AddTrueLaserTimePower", one_h, 1.0)
    assert hours(c.Classes[4]) == 1 and hours(c.StressTime) == 1
    assert c.AveragePowerFactor == pytest.approx(0.75)
    assert hours(c.TimeUsageNormalizedPower) == pytest.approx(1.5)
    assert c.LastUsage == System.DateTime.Today


def test_counter_run_time_update_clone_and_deserialization_fix():
    c = LLC.CreateDefault()
    cu.call(c, "AddRunTime", System.TimeSpan.FromHours(2))
    assert cu.call(c, "HasWorked") and hours(c.TimeInRun) == 2
    k = cu.call(c, "Clone")
    assert k.Guid == c.Guid
    other = LLC.CreateDefault()
    other.Name, other.Brand, other.Model, other.OpticalPower = "N", "B", "M", 1.0
    cu.call(c, "Update", other)
    assert (c.Name, c.Brand, c.Model) == ("N", "B", "M") and c.Guid != other.Guid
    cu.set(c, "mTimeClasses", None)
    cb = cu.clr_type(System.Runtime.Serialization.IDeserializationCallback).GetMethod("OnDeserialization")
    cb.Invoke(c, System.Array[System.Object]([None]))
    assert len(c.Classes) == 10


def test_list_clone_copies_dates():
    lst = counters()
    lst.LastSent = System.DateTime(2001, 1, 1)
    cl = LLH.GetListClone()
    assert cl.Count == 1 and cl.LastSent.Year == 2001 and not System.Object.ReferenceEquals(cl, lst)


def test_send_result_class():
    rv = LLH.RealDoSendRV()
    assert rv.UpdateResult == -1 and not rv.Success
    rv.UpdateResult = 1
    assert rv.Success


# ---------------------------------------------------------------- selection on connect
def test_on_connect_with_single_counter_selects_it():
    LLH.OnConnect(None)
    cur = cu.sget(LLH, "mCurrentLLC")
    assert cur is not None and get_setting("Last laser used") == cur.Guid
    cu.scall(LLH, "OnDisconnect")
    assert cu.sget(LLH, "mCurrentLLC") is None


def test_on_connect_with_one_alive_counter_selects_the_alive_one():
    dead = LLC.CreateDefault()
    dead.DeathDate = System.DateTime.Today
    counters().Insert(0, dead)
    LLH.OnConnect(None)
    assert cu.sget(LLH, "mCurrentLLC").Guid == counters()[1].Guid


def test_on_connect_ambiguous_needs_the_selector_dialog():
    counters().Add(LLC.CreateDefault())
    LLH.OnConnect(None)  # LaserSelector dialog needs a display: error swallowed
    assert cu.sget(LLH, "mCurrentLLC") is None
    assert get_setting("Last laser used") is None


def test_on_connect_without_counters_falls_through_to_dialog():
    counters().Clear()
    LLH.OnConnect(None)
    # Count == 0 sets null, then the else-if chain still reaches the dialog (F-07)
    assert cu.sget(LLH, "mCurrentLLC") is None


# ---------------------------------------------------------------- time accounting
def connect_counter():
    LLH.OnConnect(None)
    return cu.sget(LLH, "mCurrentLLC")


def test_run_time_accumulates_only_in_run_state():
    c = connect_counter()
    LLH.ComputeLaserTime(MS.Run)  # first sample: nothing to add
    assert c.TimeInRun.TotalSeconds == 0
    cu.sset(LLH, "mLastPowerHiResTimeNano", System.Nullable[System.Int64](nano() - 3_000_000_000))
    LLH.ComputeLaserTime(MS.Run)
    # the delta is measured from the last *power* sample, not the last status
    # sample (FINDINGS.md F-26)
    assert c.TimeInRun.TotalSeconds == pytest.approx(3, abs=0.2)
    cu.sset(LLH, "mLastPowerHiResTimeNano", System.Nullable[System.Int64](nano() - 3_000_000_000))
    LLH.ComputeLaserTime(MS.Idle)
    assert c.TimeInRun.TotalSeconds == pytest.approx(3, abs=0.2)
    assert hours(cu.scall(LLH, "GetCurrentTime")) == pytest.approx(3 / 3600, abs=1e-4)


def test_run_time_ignores_implausible_deltas():
    c = connect_counter()
    LLH.ComputeLaserTime(MS.Run)
    cu.sset(LLH, "mLastPowerHiResTimeNano", System.Nullable[System.Int64](nano() - 700_000_000_000))
    LLH.ComputeLaserTime(MS.Run)
    assert c.TimeInRun.TotalSeconds == 0


def test_true_time_uses_configured_max_pwm():
    d = Dictionary[int, str]()
    d[30] = "1000"
    GrblCore.Configuration = GrblConfST(GrblCore.GrblVersionInfo(1, 1), d)
    c = connect_counter()
    LLH.ComputeLaserTrueTime(500.0)
    cu.sset(LLH, "mLastPowerHiResTimeNano", System.Nullable[System.Int64](nano() - 10_000_000_000))
    LLH.ComputeLaserTrueTime(500.0)
    assert c.Classes[4].TotalSeconds == pytest.approx(10, abs=0.2)
    assert c.AveragePowerFactor == pytest.approx(0.5)


def test_true_time_skips_invalid_max_pwm():
    d = Dictionary[int, str]()
    d[30] = "5"
    GrblCore.Configuration = GrblConfST(GrblCore.GrblVersionInfo(1, 1), d)
    c = connect_counter()
    LLH.ComputeLaserTrueTime(1.0)
    cu.sset(LLH, "mLastPowerHiResTimeNano", System.Nullable[System.Int64](nano() - 10_000_000_000))
    LLH.ComputeLaserTrueTime(1.0)
    assert all(t.TotalSeconds == 0 for t in c.Classes)


def test_time_accounting_swallows_errors():
    cu.sset(LLH, "mLLCL", None)  # lock(null) throws
    LLH.ComputeLaserTime(MS.Run)
    LLH.ComputeLaserTrueTime(1.0)
    LLH.SaveNow()
    assert LLH.GetListClone() is None


# ---------------------------------------------------------------- CRUD + persistence
def counter_file():
    return Path(str(cu.sget(LLH, "mLLCFileName")))


def test_add_edit_death_undeath_delete_persist():
    n = LLC.CreateDefault()
    n.Name = "Second"
    cu.scall(LLH, "Add", n)
    assert counters().Count == 2 and counter_file().exists()
    edited = LLC.CreateDefault()
    cu.set(edited, "mGuid", n.Guid)
    edited.Name = "Renamed"
    cu.scall(LLH, "Edit", edited)
    assert counters()[1].Name == "Renamed"
    cu.scall(LLH, "Death", n)
    cu.scall(LLH, "Death", n)  # already dead: unchanged
    assert counters()[1].DeathDate == System.DateTime.Today
    cu.scall(LLH, "UnDeath", n)
    cu.scall(LLH, "UnDeath", n)
    assert counters()[1].DeathDate is None
    assert cu.scall(LLH, "Delete", n) is None and counters().Count == 1
    assert counter_file().with_name(counter_file().name + ".old").exists()  # previous save rotated


def test_cannot_delete_connected_counter():
    c = connect_counter()
    assert "cannot delete" in cu.scall(LLH, "Delete", c)
    assert counters().Count == 1


def test_periodic_save_is_throttled():
    cu.sset(LLH, "mLastSave", System.Int64(0))
    LLH.ComputeLaserTime(MS.Idle)  # first save is immediate (on the thread pool)
    first = cu.sget(LLH, "mLastSave")
    LLH.ComputeLaserTime(MS.Idle)
    assert cu.sget(LLH, "mLastSave") == first


# ---------------------------------------------------------------- statistics upload
@pytest.fixture
def http_sink(tmp_path):
    def start(reply):
        log = tmp_path / "posts.txt"
        p = subprocess.Popen([sys.executable, str(SUB / "http_sink.py"), reply, str(log)], stdout=subprocess.PIPE, text=True)
        port = int(p.stdout.readline())
        procs.append(p)
        return f"http://127.0.0.1:{port}/", log

    procs = []
    yield start
    for p in procs:
        p.kill()
        p.wait()


def worked_counter():
    c = counters()[0]
    cu.call(c, "AddRunTime", System.TimeSpan.FromHours(2))
    c.OpticalPower = 5.0
    c.PurchaseDate = System.DateTime(2020, 1, 2, 3, 4, 5)
    return c


def test_upload_success_records_last_sent(http_sink):
    url, log = http_sink("Success!")
    UrlManager.LaserStatistics = url
    worked_counter()
    counters().Add(LLC.CreateDefault())  # has not worked: not uploaded
    counters().LastSent = System.DateTime(2000, 1, 1)
    cu.scall(LLH, "RealDoSend", LLH.GetListClone())
    assert counters().LastSent.Year == System.DateTime.Now.Year
    body = log.read_text()
    assert "version=2" in body and "data=" in body
    data = System.Uri.UnescapeDataString(body.split("data=")[1].split("&")[0].strip().replace("+", " "))
    assert data.startswith('[ { "Guid": "') and '"Name": "Default",' in data
    assert '"OpticalPower": "5.000",' in data and '"PurchaseDate": "2020-01-02 03:04:05",' in data
    assert '"DeathDate": "",' in data and '"TimeInRun": "2.000",' in data
    # the power classes are written as an object with bare values, so the payload
    # is not valid JSON (FINDINGS.md F-27)
    assert '"Classes": { 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000, 0.000 }' in data
    with pytest.raises(json.JSONDecodeError):
        json.loads(data)


def test_upload_rejected_keeps_last_sent(http_sink):
    url, _ = http_sink("Nope")
    UrlManager.LaserStatistics = url
    worked_counter()
    counters().LastSent = System.DateTime(2000, 1, 1)
    cu.scall(LLH, "RealDoSend", LLH.GetListClone())
    assert counters().LastSent.Year == 2000


def test_upload_skipped_without_url_or_work():
    counters().LastSent = System.DateTime(2000, 1, 1)
    cu.scall(LLH, "RealDoSend", LLH.GetListClone())  # no URL
    UrlManager.LaserStatistics = "http://127.0.0.1:9/"
    cu.scall(LLH, "RealDoSend", LLH.GetListClone())  # no counter has worked
    worked_counter()
    cu.scall(LLH, "RealDoSend", LLH.GetListClone())  # connection refused: swallowed
    cu.scall(LLH, "RealDoSend", None)  # bad state: swallowed
    assert counters().LastSent.Year == 2000


def test_upload_attempt_is_scheduled_at_most_daily():
    lst = counters()
    lst.LastSent = System.DateTime(2000, 1, 1)
    lst.LastAttempt = System.DateTime(2000, 1, 1)
    LLH.ComputeLaserTime(MS.Idle)  # URL is null: the scheduled send does nothing
    assert lst.LastAttempt.Year == System.DateTime.Now.Year
    cu.sset(LLH, "mLLCL", lst)


# ---------------------------------------------------------------- static constructor (fresh processes)
def boot(mode):
    out = subprocess.run([sys.executable, str(SUB / "llc_boot.py"), mode], capture_output=True, text=True,
                         timeout=60, env=os.environ.copy())
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
    assert line, out.stdout + out.stderr
    return json.loads(line[-1])["names"]


def test_static_ctor_loads_counter_file():
    assert boot("main") == ["from-main"]


def test_static_ctor_falls_back_to_old_file():
    assert boot("old") == ["from-old"]


def test_static_ctor_adds_default_counter_to_empty_list():
    assert boot("empty") == ["Default"]
