"""LaserGRBL.Settings: static key/value store persisted with BinaryFormatter, plus
RetainedSetting<T> and the GrblCore threading-mode migration."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import System
from System.IO import FileMode, FileStream
from System.Runtime.Serialization.Formatters.Binary import BinaryFormatter
from LaserGRBL import GrblCore, Settings
from Tools import RetainedSetting

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness import runtime
from lasergrbl_harness.core_rig import fake_syncro, get_setting, settings_dict

GM = Settings.GraphicMode


def settings_file() -> Path:
    return Path(str(GrblCore.DataPath)) / "LaserGRBL.Settings.bin"


def last_cause():
    return cu.sget(Settings, "LastCause")


def read_file(path):
    fs = FileStream(str(path), FileMode.Open)
    try:
        return BinaryFormatter().Deserialize(fs)
    finally:
        fs.Close()


# ---------------------------------------------------------------- get / set / delete
def test_get_object_returns_default_for_missing_wrong_type_or_null():
    Settings.SetObject("i", System.Int32(5))
    Settings.SetObject("n", None)
    assert Settings.GetObject[System.Int32]("i", 0) == 5
    assert Settings.GetObject[System.String]("i", "dflt") == "dflt"  # stored type differs
    assert Settings.GetObject[System.String]("n", "dflt") == "dflt"
    assert Settings.GetObject[System.Int32]("missing", 7) == 7


def test_get_object_swallows_errors():
    saved = settings_dict()
    cu.sset(Settings, "dic", None)
    try:
        assert Settings.GetObject[System.Int32]("x", 3) == 3
    finally:
        cu.sset(Settings, "dic", saved)


def test_set_object_triggers_save_only_on_change():
    Settings.SetObject("k", 1)
    assert last_cause() == "k"
    cu.sset(Settings, "LastCause", None)
    Settings.SetObject("k", 1)
    assert last_cause() is None
    Settings.SetObject("k", 1, True)  # force
    assert last_cause() == "k"
    cu.sset(Settings, "LastCause", None)
    Settings.SetObject("k", 2)
    assert last_cause() == "k"


def test_set_object_compares_object_arrays_by_content():
    a = System.Array[System.Object]([1, "x"])
    Settings.SetObject("arr", a)
    cu.sset(Settings, "LastCause", None)
    Settings.SetObject("arr", System.Array[System.Object]([1, "x"]))
    assert last_cause() is None
    Settings.SetObject("arr", System.Array[System.Object]([1, "y"]))
    assert last_cause() == "arr"


def test_arrays_equal_helper():
    m = cu.clr_type(Settings).GetMethod("ArraysEqual", cu.STAT).MakeGenericMethod(cu.clr_type(System.Object))

    def eq(a, b):
        return m.Invoke(None, System.Array[System.Object]([a, b]))

    a = System.Array[System.Object]([1, 2])
    assert eq(a, a)
    assert not eq(a, None) and not eq(None, a)
    assert not eq(a, System.Array[System.Object]([1]))
    assert not eq(a, System.Array[System.Object]([1, 3]))
    assert eq(a, System.Array[System.Object]([1, 2]))


def test_get_and_delete_object():
    Settings.SetObject("g", "v")
    Settings.SetObject("gn", None)
    assert Settings.GetAndDeleteObject("g", "d") == "v"
    assert not cu.scall(Settings, "ExistObject", "g")
    assert Settings.GetAndDeleteObject("gn", "d") == "d"
    assert Settings.GetAndDeleteObject("missing", "d") == "d"
    cu.scall(Settings, "DeleteObject", "missing")  # no-op


def test_exiting_writes_settings_file_immediately():
    Settings.SetObject("persist-me", "yes")
    cu.scall(Settings, "Exiting")
    data = read_file(settings_file())
    assert data["persist-me"] == "yes"
    assert last_cause() is None
    cu.scall(Settings, "Exiting")  # nothing pending: no write


def test_save_failure_is_swallowed():
    f = settings_file()
    backup = f.with_suffix(".bak-test")
    if f.exists():
        shutil.move(f, backup)
    f.mkdir()  # the target path is a directory -> FileStream fails
    try:
        Settings.SetObject("x", 1)
        cu.scall(Settings, "Exiting")
    finally:
        f.rmdir()
        if backup.exists():
            shutil.move(backup, f)
    assert last_cause() is None


def test_settings_file_is_copied_from_working_directory_when_missing(tmp_path, monkeypatch):
    # (CLR-typed values: a Python int would be boxed as a non-serializable PyInt)
    Settings.SetObject("seed", System.Int32(1))
    cu.scall(Settings, "Exiting")  # make sure a valid settings file exists
    f = settings_file()
    backup = f.with_suffix(".bak-test")
    shutil.move(f, backup)
    shutil.copy(backup, tmp_path / "LaserGRBL.Settings.bin")
    monkeypatch.chdir(tmp_path)
    try:
        Settings.SetObject("after-copy", System.Int32(1))
        cu.scall(Settings, "Exiting")  # filename getter copies ./LaserGRBL.Settings.bin first
        assert f.exists()
        assert read_file(f)["after-copy"] == 1
    finally:
        if backup.exists():
            os.replace(backup, f)


def test_graphic_modes():
    assert Settings.ConfiguredGraphicMode == GM.AUTO
    Settings.ConfiguredGraphicMode = GM.DIB
    assert Settings.ConfiguredGraphicMode == GM.DIB and Settings.RequestedGraphicMode == GM.DIB
    Settings.ForcedGraphicMode = GM.GDI
    try:
        assert Settings.RequestedGraphicMode == GM.GDI
    finally:
        Settings.ForcedGraphicMode = GM.AUTO
    Settings.CurrentGraphicMode = GM.FBO
    assert Settings.CurrentGraphicMode == GM.FBO
    Settings.CurrentGraphicMode = GM.AUTO


# ---------------------------------------------------------------- static constructor (fresh processes)
SUB = Path(__file__).parent / "subproc" / "settings_boot.py"


def boot(mode):
    out = subprocess.run([sys.executable, str(SUB), mode], capture_output=True, text=True, timeout=60, env=os.environ.copy())
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
    assert line, out.stdout + out.stderr
    return json.loads(line[-1])


def test_static_ctor_with_existing_file_reads_previous_version():
    # this test process was started with a seeded settings file (conftest.py)
    assert not Settings.IsNewFile
    assert str(Settings.PrevVersion) == "4.4.0"


def test_static_ctor_without_file_starts_empty():
    r = boot("new")
    assert r["is_new"] and r["prev"] == "0.0.0"
    assert r["keys"] == ["Current LaserGRBL Version"]


def test_static_ctor_with_corrupt_file_starts_empty():
    r = boot("corrupt")
    assert not r["is_new"] and r["prev"] == "0.0.0"
    assert r["keys"] == ["Current LaserGRBL Version"]


def test_new_settings_file_skips_threading_migration():
    assert boot("new")["threading"] == "None"  # nothing stored, nothing migrated


def test_settings_from_4_6_keep_insane_threading_mode():
    r = boot("v46")
    assert r["prev"] == "4.6.0" and r["threading"] == "Insane"


# ---------------------------------------------------------------- RetainedSetting / threading migration
def test_retained_setting_reads_default_and_persists_changes():
    rs = RetainedSetting[System.Boolean]("rs-test", True)
    assert rs.Value
    rs.Value = True  # unchanged: no write, no event
    assert get_setting("rs-test") is True  # written once by the constructor
    rs.Value = False
    assert get_setting("rs-test") is False


def test_old_insane_threading_mode_is_migrated_to_fast():
    Settings.SetObject("Threading Mode", GrblCore.ThreadingMode.UltraFast)
    GrblCore(fake_syncro(), None, None)
    assert str(get_setting("Threading Mode")) == "Fast"


def test_slow_threading_mode_is_kept():
    Settings.SetObject("Threading Mode", GrblCore.ThreadingMode.Slow)
    GrblCore(fake_syncro(), None, None)
    assert str(get_setting("Threading Mode")) == "Slow"


def test_threading_mode_values():
    TM = GrblCore.ThreadingMode
    modes = [TM.Slow, TM.Quiet, TM.Fast, TM.UltraFast, TM.Insane]
    assert [m.StatusQuery for m in modes] == [2000, 1000, 500, 250, 200]
    assert [str(m) for m in modes] == ["Slow", "Quiet", "Fast", "UltraFast", "Insane"]
    assert TM.Fast.Equals(TM.Fast) and not TM.Fast.Equals(TM.Slow) and not TM.Fast.Equals(None)
    assert isinstance(TM.Fast.GetHashCode(), int)
    assert (TM.Slow.TxLong, TM.Slow.TxShort, TM.Slow.RxLong, TM.Slow.RxShort) == (15, 4, 2, 1)
