"""GrblCore receive path (ManageReceivedLine), driven line by line without threads."""

import pytest

import System
from LaserGRBL import GrblCommand, GrblCore, GrblMessage, Settings

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness.core_rig import MacStatus, get_setting

V = GrblCore.GrblVersionInfo
Issue = GrblCore.DetectedIssue


@pytest.fixture
def r(rigs):
    rig = rigs()
    rig.open_stepped(MacStatus.Idle)
    return rig


def set_version(v):
    Settings.SetObject("Last GrblVersion known", v)


def in_program(rig, lines=3):
    """Put the core 'in program' without a file: start the time projection."""
    from LaserGRBL import GrblFile

    q = System.Collections.Generic.Queue[GrblCommand]()
    for _ in range(lines):
        q.Enqueue(GrblCommand("G0"))
    rig.tp.JobStart(GrblFile(), q, True)


def pend(rig, text="G1 X1"):
    """Enqueue and send one command so it is waiting for a response."""
    rig.core.EnqueueCommand(GrblCommand(text))
    rig.send_line()
    return rig.pending.Peek()


def last_sent(rig):
    return rig.sent[rig.sent.Count - 1]


# ---------------------------------------------------------------- command responses
def test_ok_completes_oldest_pending_and_frees_buffer(r):
    c = pend(r, "G1 X10")
    assert r.core.UsedBuffer == len("G1X10\n")
    r.rx("ok")
    assert c.Status == GrblCommand.CommandStatus.ResponseGood
    assert r.pending.Count == 0 and r.core.UsedBuffer == 0


def test_error_marks_command_bad(r):
    c = pend(r)
    r.rx("error:20")
    assert c.Status == GrblCommand.CommandStatus.ResponseBad
    assert c.GetResult(False, False) == "ERROR:20"


def test_response_without_pending_command_is_ignored(r):
    r.rx("ok")
    r.rx("ERROR:1")
    assert r.sent.Count == 0 and r.core.UsedBuffer == 0


def test_used_buffer_never_goes_negative(r):
    pend(r)
    cu.set(r.core, "mUsedBuffer", 2)
    r.rx("ok")
    assert r.core.UsedBuffer == 0


def test_broken_ok_counts_as_ok_and_logs_warning(r):
    c = pend(r)
    r.rx("xokx")
    assert c.Status == GrblCommand.CommandStatus.ResponseGood
    texts = r.sent_texts()
    assert "Handle broken ok!" in texts


def test_eeprom_write_ok_updates_stored_configuration(r):
    set_version(V(1, 1, "f"))
    from LaserGRBL import GrblConfST

    stored = GrblConfST(V(1, 1, "f"))
    stored.AddOrUpdate("$0=10")
    GrblCore.Configuration = stored
    pend(r, "$110=1234")
    r.rx("ok")
    assert float(str(GrblCore.Configuration.MaxRateX)) == 1234


def test_eeprom_write_is_lost_when_no_configuration_was_read_yet(r):
    set_version(V(1, 1, "f"))
    pend(r, "$110=1234")
    r.rx("ok")
    # Configuration returns a fresh default object when none is stored; the update
    # is applied to that temporary and lost (FINDINGS.md F-16)
    assert GrblCore.Configuration.Count == 0


def test_eeprom_write_error_does_not_update_configuration(r):
    set_version(V(1, 1, "f"))
    pend(r, "$110=1234")
    r.rx("error:3")
    assert GrblCore.Configuration.Count == 0


def test_response_exception_is_swallowed(r):
    c = pend(r)
    cu.set(r.core, "mPending", None)  # force a NullReferenceException inside the handler
    r.rx("ok")
    cu.set(r.core, "mPending", System.Collections.Generic.Queue[GrblCommand]())
    assert c.Status == GrblCommand.CommandStatus.WaitingResponse


# ---------------------------------------------------------------- welcome / version detection
def test_standard_welcome_sets_version_and_resets_state(r):
    r.core.EnqueueCommand(GrblCommand("G0 X1"))
    r.core.TOverrideG1 = 150
    r.rx("Grbl 1.1h ['$' for help]")
    assert str(r.core.GrblVersion) == "1.1h"
    assert r.queue.Count == 0 and r.core.TOverrideG1 == 100
    assert r.sent_texts()[-1] == "Grbl 1.1h ['$' for help]"
    assert "override" in r.events


def test_welcome_during_running_program_is_an_unexpected_reset(r):
    in_program(r)
    r.set_status(MacStatus.Run)
    r.rx("Grbl 1.1f ['$' for help]")
    assert "issue:UnexpectedReset" in r.events
    assert not r.core.InProgram


def test_malformed_welcome_is_logged_not_fatal(r):
    r.rx("Grbl x.yz")
    assert r.core.GrblVersion is None
    assert r.sent_texts() == ["Grbl x.yz"]


def test_grblhal_welcome(r):
    r.rx("GrblHAL 1.1f ['$' or '$HELP' for help]")
    v = r.core.GrblVersion
    assert v.IsHAL and str(v) == "1.1f"


def test_grblhal_malformed(r):
    r.rx("GrblHAL bad")
    assert r.core.GrblVersion is None


def test_vigo_welcome_sets_vendor_and_build(r):
    r.rx("Grbl-Vigo:1.1f|Build:G-20170131-V3.0-20200720")
    v = r.core.GrblVersion
    assert v.MachineName == "Grbl-Vigo" and str(v) == "1.1f"
    assert cu.get(r.core, "mVendorVersionSeen") == "G-20170131-V3.0-20200720"


def test_vigo_malformed(r):
    r.rx("Grbl-Vigo:x")
    assert r.core.GrblVersion is None


def test_ortur_model_firmware_then_welcome(r):
    r.rx("Ortur Laser Master 3 Ready!")
    r.rx("OLF 182.")
    r.rx("Grbl 1.1f ['$' for help]")
    v = r.core.GrblVersion
    assert v.IsOrtur and v.MachineName == "Ortur Laser Master 3" and v.OrturFWVersionNumber == 182
    assert r.core.IsOrturBoard and not r.core.IsLongerBoard


def test_aufero_model_is_handled_as_ortur(r):
    r.rx("Aufero AL1 Ready!")
    r.rx("Grbl 1.1f ['$' for help]")
    assert r.core.GrblVersion.IsOrtur


def test_longer_machine_and_software(r):
    r.rx("[Machine:Longer Nano]")
    assert r.core.GrblVersion.IsLonger and r.core.IsLongerBoard
    r.rx("[Software:V1.2.3]")
    assert cu.get(r.core, "mVendorVersionSeen") == "V1.2.3"
    assert str(r.core.GrblVersion) == "1.1f"


def test_simplelaser_welcome(r):
    r.rx("SimpleLaser 1.1f ['$' for help]")
    assert r.core.GrblVersion.MachineName == "SimpleLaser"


def test_simplelaser_malformed(r):
    r.rx("SimpleLaser zz")
    assert r.core.GrblVersion is None


def test_unknown_firmware_welcome_detected_by_regex_once(r):
    r.rx("FluidNC 3.7x")
    v = r.core.GrblVersion
    assert v.MachineName == "FluidNC" and str(v) == "3.7x"
    r.rx("Other 2.0a")  # a welcome was already seen: plain message now
    assert str(r.core.GrblVersion) == "3.7x"


def test_unknown_welcome_parse_failure_is_swallowed(r):
    r.rx("Fw 99999999999.1a")
    assert r.core.GrblVersion is None
    assert cu.get(r.core, "mWelcomeSeen") == "Fw 99999999999.1a"


def test_version_change_reloads_csv_and_logs(r):
    set_version(V(1, 1, "f"))
    r.rx("Grbl 0.9j ['$' for help]")
    assert str(r.core.GrblVersion) == "0.9j"
    assert not r.core.SupportCSV and not r.core.SupportRTO and not r.core.SupportOverride
    assert not r.core.SupportLaserMode and not r.core.SupportTrueJogging


def test_version_support_flags_for_v11(r):
    set_version(V(1, 1, "f"))
    assert r.core.SupportCSV and r.core.SupportRTO and r.core.SupportOverride and r.core.SupportLaserMode
    assert r.core.SupportTrueJogging


# ---------------------------------------------------------------- other messages
def test_alarm_message_during_program_raises_machine_alarm_issue(r):
    in_program(r)
    r.rx("ALARM:1")
    assert "issue:MachineAlarm" in r.events
    assert cu.type_name(last_sent(r)) == "GrblMessage"


def test_alarm_outside_program_is_just_logged(r):
    r.rx("ALARM:2")
    assert not any(e.startswith("issue") for e in r.events)
    assert r.sent_texts() == ["ALARM:2"]


def test_alarm_message_is_decoded_when_version_supports_csv(r):
    set_version(V(1, 1, "f"))
    r.rx("ALARM:1")
    assert r.sent_texts() == ["Hard limit"]


def test_sta_ip_message_records_ip(r):
    r.rx("[MSG:Get IP 192.168.1.182]")
    assert r.core.DetectedIP == "192.168.1.182"


def test_longer_ip_message_records_ip(r):
    r.rx("[MSG:Connected with 10.0.0.7]")
    assert r.core.DetectedIP == "10.0.0.7"


def test_generic_message_is_logged(r):
    r.rx("[MSG:Caution: Unlocked]")
    assert r.sent_texts() == ["[MSG:Caution: Unlocked]"]


def test_generic_message_exception_is_swallowed(r):
    cu.set(r.core, "mSentPtr", None)
    r.rx("[MSG:x]")
    r.rx("[MSG:Get IP 1.2.3.4]")
    r.rx("[MSG:Connected with 1.2.3.4]")
    cu.set(r.core, "mSentPtr", cu.get(r.core, "mSent"))
    assert r.core.DetectedIP == "1.2.3.4"


def test_ip_message_too_short_is_swallowed(r):
    cu.call(r.core, "ManageStaIPMessage", "[MSG:Get IP")
    cu.call(r.core, "ManageLongerIPMessage", "[MSG:Connected")
    assert r.core.DetectedIP is None


@pytest.mark.parametrize("name", ["ManageOrturModelMessage", "ManageLongerModelMessage",
                                  "ManageLongerFirmwareMessage", "ManageOrturFirmwareMessage"])
def test_vendor_message_handlers_catch_parse_errors(r, name):
    # The received line is never null in practice (the RX loop skips empty lines);
    # a null line is the only way to reach these defensive catch blocks. The
    # GrblMessage built *after* the try block then throws.
    with pytest.raises(System.NullReferenceException):
        cu.call(r.core, name, None)
    assert r.core.GrblVersion is None


# ---------------------------------------------------------------- status reports (Grbl 1.1)
def test_status_report_parses_all_fields(r):
    set_version(V(1, 1, "f"))
    r.rx("<Idle|MPos:1.000,2.000,3.000|Bf:15,128|FS:500,250|WCO:0.500,1.000,0.000|Ov:110,50,90>")
    mp, wco, wp = r.core.MachinePosition, r.core.WorkingOffset, r.core.WorkPosition
    assert (mp.X, mp.Y, mp.Z) == (1, 2, 3)
    assert (wco.X, wco.Y, wco.Z) == (0.5, 1, 0)
    assert (wp.X, wp.Y, wp.Z) == (0.5, 1, 3)
    assert (r.core.CurrentF, r.core.CurrentS) == (500, 250)
    assert (r.core.OverrideG1, r.core.OverrideG0, r.core.OverrideS) == (110, 50, 90)
    assert (r.core.GrblBlock, r.core.GrblBuffer) == (15, 128)
    assert r.core.BufferSize == 128 and r.core.FreeBuffer == 128


def test_status_report_wpos_is_converted_with_known_wco(r):
    set_version(V(1, 1, "f"))
    r.rx("<Idle|MPos:0,0,0|WCO:10,20,0>")
    r.rx("<Run|WPos:1.000,2.000,3.000|F:300>")
    mp = r.core.MachinePosition
    assert (mp.X, mp.Y, mp.Z) == (11, 22, 3)
    assert r.core.CurrentF == 300 and r.core.CurrentS == 0
    assert r.core.MachineStatus == MacStatus.Run


def test_status_report_with_short_coordinate_list(r):
    set_version(V(1, 1, "f"))
    r.rx("<Idle|MPos:1,2|FS:7>")
    mp = r.core.MachinePosition
    assert (mp.X, mp.Y, mp.Z) == (1, 2, 0)
    assert (r.core.CurrentF, r.core.CurrentS) == (7, 0)


def test_status_version_guessed_from_report_when_unknown(r):
    r.rx("<Jog|MPos:1,2,3>")
    assert r.core.MachineStatus == MacStatus.Jog and r.core.MachinePosition.X == 1


def test_legacy_status_report_v09(r):
    r.rx("<Idle,MPos:5.000,6.000,7.000,WPos:1.000,2.000,3.000>")
    mp, wco = r.core.MachinePosition, r.core.WorkingOffset
    assert (mp.X, mp.Y, mp.Z) == (5, 6, 7)
    assert (wco.X, wco.Y, wco.Z) == (4, 4, 4)


def test_legacy_status_report_status_only(r):
    r.rx("<Alarm>")
    assert r.core.MachineStatus == MacStatus.Alarm


def test_pin_report_with_unknown_version_is_not_parsed(r):
    # '|' + 'Pin:' -> guessed 1.0c -> parsed with the comma format, which fails on
    # "Idle|MPos" and is swallowed: nothing is updated (FINDINGS.md F-15)
    r.rx("<Idle|MPos:1.000,2.000,3.000|Pin:XYZ>")
    assert r.core.MachineStatus == MacStatus.Idle and r.core.MachinePosition.X == 0


def test_unknown_machine_state_is_swallowed(r):
    set_version(V(1, 1, "f"))
    r.rx("<Sleep|MPos:9,9,9>")
    assert r.core.MachineStatus == MacStatus.Idle and r.core.MachinePosition.X == 0


def test_idle_during_program_is_reported_as_run(r):
    set_version(V(1, 1, "f"))
    in_program(r)
    r.rx("<Idle|MPos:0,0,0>")
    assert r.core.MachineStatus == MacStatus.Run


def test_hold_states_depend_on_who_requested_it(r):
    set_version(V(1, 1, "f"))
    r.set_status(MacStatus.Run)
    r.rx("<Hold:0|MPos:0,0,0>")
    assert r.core.MachineStatus == MacStatus.AutoHold  # not requested by user
    r.set_status(MacStatus.Run)
    r.core.FeedHold(False)
    r.rx("<Hold:0|MPos:0,0,0>")
    assert r.core.MachineStatus == MacStatus.Hold
    r.set_status(MacStatus.Run)  # leaving a hold state clears the request flags
    r.core.FeedHold(True)
    r.rx("<Hold:1|MPos:0,0,0>")
    assert r.core.MachineStatus == MacStatus.Cooling


def test_status_change_raises_event_and_updates_last_activity(r):
    set_version(V(1, 1, "f"))
    r.rx("<Run|MPos:1,0,0>")
    assert "status:Run" in r.events
    elapsed = cu.get(r.core, "debugLastMoveOrActivityDelay").ElapsedTime
    assert elapsed.TotalSeconds < 5


def test_buffer_auto_size_only_accepts_known_values_once(r):
    set_version(V(1, 1, "f"))
    r.rx("<Idle|MPos:0,0,0|Bf:15,100>")
    assert r.core.BufferSize == 127  # unknown value ignored
    for size in (255, 256, 10240, 254, 128):
        cu.set(r.core, "mAutoBufferSize", 127)
        r.rx(f"<Idle|MPos:0,0,0|Bf:15,{size}>")
        assert r.core.BufferSize == size
    r.rx("<Idle|MPos:0,0,0|Bf:15,255>")
    assert r.core.BufferSize == 128  # already changed: not changed again


def test_wco_is_remembered_for_job_resume_only_in_program(r):
    set_version(V(1, 1, "f"))
    r.rx("<Idle|MPos:0,0,0|WCO:1,1,1>")
    assert r.tp.LastKnownWCO.X == 0
    in_program(r)
    r.rx("<Run|MPos:0,0,0|WCO:2,2,2>")
    assert r.tp.LastKnownWCO.X == 2


# ---------------------------------------------------------------- overrides
def ov(rig, cur, target):
    rig.core.TOverrideG1, rig.core.TOverrideG0, rig.core.TOverrideS = target
    before = len(rig.device.realtime)
    rig.rx(f"<Idle|MPos:0,0,0|Ov:{cur[0]},{cur[1]},{cur[2]}>")
    rig.link.pump()
    return rig.device.realtime[before:]


@pytest.mark.parametrize(
    "cur,target,sent",
    [
        ((100, 100, 100), (100, 100, 100), []),
        ((120, 100, 100), (100, 100, 100), [0x90]),
        ((100, 100, 100), (110, 100, 100), [0x91]),
        ((120, 100, 100), (110, 100, 100), [0x92]),
        ((100, 100, 100), (105, 100, 100), [0x93]),
        ((105, 100, 100), (101, 100, 100), [0x94]),
        ((100, 100, 120), (100, 100, 100), [0x99]),
        ((100, 100, 100), (100, 100, 130), [0x9A]),
        ((100, 100, 130), (100, 100, 110), [0x9B]),
        ((100, 100, 100), (100, 100, 102), [0x9C]),
        ((100, 100, 102), (100, 100, 100), [0x99]),
        ((100, 100, 103), (100, 100, 101), [0x9D]),
        ((100, 25, 100), (100, 100, 100), [0x95]),
        ((100, 100, 100), (100, 50, 100), [0x96]),
        ((100, 100, 100), (100, 25, 100), [0x97]),
        ((100, 50, 100), (100, 75, 100), []),
        ((90, 50, 95), (100, 100, 100), [0x90, 0x99, 0x95]),
    ],
)
def test_overrides_step_towards_target(r, cur, target, sent):
    set_version(V(1, 1, "f"))
    assert ov(r, cur, target) == sent


def test_override_change_raises_event_only_on_change(r):
    set_version(V(1, 1, "f"))
    r.rx("<Idle|MPos:0,0,0|Ov:100,100,100>")
    assert "override" not in r.events
    r.rx("<Idle|MPos:0,0,0|Ov:110,100,100>")
    assert r.events.count("override") == 1


@pytest.mark.parametrize(
    "action,attr,start,expected",
    [
        ("OverridePowerDefault", "TOverrideS", 150, 100),
        ("OverridePowerUp", "TOverrideS", 200, 200),
        ("OverridePowerUp", "TOverrideS", 100, 101),
        ("OverridePowerDown", "TOverrideS", 10, 10),
        ("OverridePowerDown", "TOverrideS", 100, 99),
        ("OverrideLinearDefault", "TOverrideG1", 150, 100),
        ("OverrideLinearUp", "TOverrideG1", 199, 200),
        ("OverrideLinearDown", "TOverrideG1", 11, 10),
        ("OverrideRapidDefault", "TOverrideG0", 25, 100),
        ("OverrideRapidUp", "TOverrideG0", 25, 50),
        ("OverrideRapidUp", "TOverrideG0", 100, 100),
        ("OverrideRapidDown", "TOverrideG0", 100, 50),
        ("OverrideRapidDown", "TOverrideG0", 25, 25),
        ("JogHome", "TOverrideG1", 123, 123),  # non-override action: no change
    ],
)
def test_hotkey_override_targets(r, action, attr, start, expected):
    from LaserGRBL import HotKeysManager

    setattr(r.core, attr, start)
    cu.call(r.core, "HotKeyOverride", getattr(HotKeysManager.HotKey.Actions, action))
    assert getattr(r.core, attr) == expected
