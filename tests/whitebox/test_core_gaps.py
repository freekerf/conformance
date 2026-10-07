"""Remaining GrblCore behaviours: file dispatch by extension (headless), project
files, wrapper selection, reply-order tolerance of the $$/$I readers, permission
matrix and small helpers."""

import base64
import os

import pytest

import System
from System.Collections.Generic import Dictionary, List
from System.IO import FileMode, FileStream
from System.Runtime.Serialization.Formatters.Binary import BinaryFormatter
from LaserGRBL import GrblCommand, GrblConfST, GrblCore, Settings
from LaserGRBL.ComWrapper import WrapperType

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus, get_setting, load_file_sync
from lasergrbl_harness.fake_grbl import FakeGrbl

V = GrblCore.GrblVersionInfo
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


@pytest.fixture
def r(rigs):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    rig.open_stepped(MacStatus.Idle)
    return rig


@pytest.fixture
def gcode(tmp_path):
    def make(lines, name="g.nc"):
        p = tmp_path / name
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    return make


# ---------------------------------------------------------------- headless file dispatch
@pytest.mark.parametrize("ext", [".png", ".svg", ".dxf", ".txt"])
def test_open_file_dispatch_never_throws_headless(r, tmp_path, ext):
    # every non-G-code branch ends in a WinForms dialog/MessageBox; without a
    # display the error is logged and the call returns normally
    p = tmp_path / ("x" + ext)
    p.write_bytes(PNG_1PX if ext == ".png" else b"<svg/>" if ext == ".svg" else b"0\nEOF\n")
    r.core.OpenFile(str(p), False)
    assert r.core.LoadedFile.Count == 0
    assert str(get_setting("Core.LastOpenFile")) == str(p)


def test_reopen_last_file(r, gcode):
    path = gcode(["G0 X1"])
    Settings.SetObject("Core.LastOpenFile", path)
    assert r.core.CanReOpenFile
    r.core.ReOpenFile()  # dispatches to OpenFile(.nc): needs the wait cursor -> logged
    assert r.core.LoadedFile.Count == 0


def test_project_file_restores_settings_and_opens_each_image(r, tmp_path):
    def item(name, extra):
        d = Dictionary[System.String, System.Object]()
        d["ImageName"] = name
        d["ImageBase64"] = base64.b64encode(PNG_1PX).decode()
        for k, v in extra.items():
            d[k] = v
        return d

    project = List[Dictionary[System.String, System.Object]]()
    project.Add(item("one.png", {"GrayScaleConversion": "Simple", "proj-flag": System.Int32(7)}))
    project.Add(item("two.png", {}))
    lps = tmp_path / "p.lps"
    fs = FileStream(str(lps), FileMode.Create)
    BinaryFormatter().Serialize(fs, project)
    fs.Close()
    r.core.OpenFile(str(lps), False)
    assert get_setting("proj-flag") == 7 and get_setting("GrayScaleConversion") == "Simple"
    # the last image becomes the "last open file" (written with a '\\' separator, F-11)
    assert str(get_setting("Core.LastOpenFile")).endswith("\\two.png")


def test_new_project_is_ignored_without_program_or_history(r):
    assert not r.core.CanNewProject
    r.core.NewProject()


# ---------------------------------------------------------------- job start variants
def test_run_from_start_with_homing_pushes_dollar_h_first(r, gcode):
    load_file_sync(r.core.LoadedFile, gcode(["G0 X1"]))
    cu.call(r.core, "RunProgramFromStart", True, True, False)
    assert r.queue_texts()[:2] == ["$H", "G90 (use absolute coordinates)"]


def test_restart_from_the_start_after_an_interruption_skips_the_header(r, gcode):
    # the resume dialog with position 0 calls RunProgramFromStart(homing) with
    # first=false: the custom header is not queued (FINDINGS.md F-54); RunProgram
    # (a job never started or already completed) queues it
    load_file_sync(r.core.LoadedFile, gcode(["G0 X1"]))
    cu.call(r.core, "RunProgramFromStart", True, False, False)
    assert r.queue_texts() == ["$H", "G0 X1"]


def test_job_end_notifies_telegram_when_over_threshold(r, gcode):
    Settings.SetObject("TelegramNotification.Threshold", System.Int32(0))
    load_file_sync(r.core.LoadedFile, gcode(["G0 X1"]))
    r.core.RunProgram(None)
    r.pump()  # Telegram.NotifyEvent is a no-op unless notifications are enabled
    assert not r.core.InProgram


# ---------------------------------------------------------------- wrappers
@pytest.mark.parametrize("kind,args", [
    ("UsbSerial", ["/dev/null", 115200]), ("UsbSerial2", ["/dev/null", 115200]), ("RJCPSerial", ["/dev/null", 115200]),
    ("Telnet", ["127.0.0.1:23"]), ("LaserWebESP8266", ["ws://127.0.0.1:81/"]), ("Emulator", []),
])
def test_configure_selects_wrapper_type_once(rigs, kind, args):
    rig = rigs()
    conv = [System.Int32(a) if isinstance(a, int) else a for a in args]
    rig.core.Configure(getattr(WrapperType, kind), System.Array[System.Object](conv))
    first = cu.get(rig.core, "com")
    assert first.GetType().Name == kind
    rig.core.Configure(getattr(WrapperType, kind), System.Array[System.Object](conv))
    assert System.Object.ReferenceEquals(cu.get(rig.core, "com"), first)  # same type: reused


# ---------------------------------------------------------------- reply order tolerance
def test_late_settings_and_info_within_500ms_are_collected(rigs):
    rig = rigs(device=FakeGrbl(ok_first=True, data_delay=0.1, report_buffer=False), link="pty")
    rig.connect()
    assert GrblCore.Configuration.Count == len(rig.device.settings)
    assert rig.core.BufferSize == 128


def test_settings_arriving_after_500ms_are_missed(rigs):
    rig = rigs(device=FakeGrbl(ok_first=True, data_delay=0.8, report_buffer=False), link="pty")
    rig.connect()
    # the readers give up 500 ms after the last reply; late lines become log messages
    assert GrblCore.Configuration.Count == 0 and rig.core.BufferSize == 127


def test_settings_and_info_read_when_ok_comes_first(rigs):
    rig = rigs(device=FakeGrbl(ok_first=True, report_buffer=False), link="pty")
    rig.connect()
    assert GrblCore.Configuration.Count == len(rig.device.settings)
    assert rig.core.BufferSize == 128


# ---------------------------------------------------------------- permission matrix
STATES = ["Disconnected", "Connecting", "Idle", "Run", "Hold", "Door", "Alarm", "Check", "Jog", "Cooling", "AutoHold"]


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("program", [False, True])
def test_permission_matrix(rigs, gcode, state, program):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(1, 1, "f"))
    rig.com.ForceOpen(True)
    if program:
        load_file_sync(rig.core.LoadedFile, gcode(["G0 X1"]))
    cu.set(rig.core, "mMachineStatus", getattr(MacStatus, state))
    c = rig.core
    connected = state not in ("Disconnected", "Connecting")
    hold = state in ("Hold", "Cooling", "AutoHold")
    assert c.IsConnected == connected
    assert c.CanResetGrbl == connected
    assert c.CanSendManualCommand == connected
    assert c.CanImportExport == (connected and state == "Idle")
    assert c.CanUnlock == (state in ("Idle", "Alarm"))
    assert c.CanFeedHold == (state == "Run")
    assert c.CanResumeHold == (state == "Door" or hold)
    assert c.CanReadWriteConfig == (state in ("Idle", "Alarm"))
    assert c.CanSendFile == (program and state in ("Idle", "Check"))
    assert c.CanAbortProgram == (program and connected and (state == "Run" or hold))
    assert c.CanDoHoming == (state in ("Idle", "Alarm"))
    assert c.JogEnabled == (state in ("Idle", "Jog"))
    assert c.CanNewProject == program and c.CanLoadNewFile


def test_jog_enabled_legacy_firmware_in_program(rigs, gcode):
    rig = rigs()
    Settings.SetObject("Last GrblVersion known", V(0, 9, "j"))
    rig.open_stepped(MacStatus.Idle)
    load_file_sync(rig.core.LoadedFile, gcode(["G0 X1"]))
    rig.core.RunProgram(None)
    rig.set_status(MacStatus.Run)
    assert not rig.core.JogEnabled  # in a program


# ---------------------------------------------------------------- helpers
def test_temp_path_is_created_on_first_use(tmp_path):
    cu.sset(GrblCore, "mTempPath", None)
    path = str(GrblCore.TempPath)
    os.rmdir(path) if os.path.isdir(path) and not os.listdir(path) else None
    cu.sset(GrblCore, "mTempPath", None)
    assert os.path.isdir(str(GrblCore.TempPath))


def test_exe_path_without_entry_assembly():
    # Application.ExecutablePath needs the entry assembly; under pythonnet there is
    # none, so the property throws (it works inside the real application)
    with pytest.raises(Exception):
        GrblCore.ExePath


def test_hotkeys_are_delegated_to_the_manager(r):
    import System.Windows.Forms as WF

    # the call reaches HotKeysManager, which needs the PreviewForm the harness does
    # not provide (the manager is UI code, out of scope)
    with pytest.raises(System.NullReferenceException):
        cu.call(r.core, "ManageHotKeys", None, getattr(WF.Keys, "None"))


def test_conf_string_with_version_but_missing_key():
    assert GrblConfST(V(1, 1)).WiFi_SSID is None


def test_threading_mode_equals_other_types():
    assert not GrblCore.ThreadingMode.Fast.Equals("Fast")


def test_set_object_array_against_non_array():
    Settings.SetObject("mix", "text")
    Settings.SetObject("mix", System.Array[System.Object](["text"]))
    assert get_setting("mix").Length == 1


def test_upload_json_separates_multiple_counters(tmp_path):
    import LaserGRBL

    LLH = getattr(LaserGRBL, "LaserLifeHandler")
    lst = List[LLH.LaserLifeCounter]()
    for name in ("a", "b"):
        c = LLH.LaserLifeCounter.CreateDefault()
        c.Name = name
        lst.Add(c)
    js = str(cu.scall(LLH, "BuildJson", lst))
    assert js.count('"Guid"') == 2 and ' }, { ' in js and js.endswith(" }  ]")
