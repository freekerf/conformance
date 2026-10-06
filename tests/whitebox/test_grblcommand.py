"""GrblCommand / GrblMessage / CSVD: parsing and classification of single G-code lines."""

import pytest

import System
from LaserGRBL import CSVD, ColorScheme, GrblCommand, GrblCore, GrblMessage
from LaserGRBL.CSV import CsvDictionary

from lasergrbl_harness import clr_util as cu

Status = GrblCommand.CommandStatus
MT = GrblMessage.MessageType


def built(line, **kw):
    c = GrblCommand(line, **kw)
    c.BuildHelper()
    return c


def num(e):
    return None if e is None else float(str(e.Number))


# ---------------------------------------------------------------- construction / text
def test_command_text_is_trimmed_and_uppercased():
    assert GrblCommand("  g1 x1.5 y-2 \r\n").Command == "G1 X1.5 Y-2"


def test_preservecase_keeps_original_case():
    assert GrblCommand(" $sta/ssid=MyNet ", 0, True).Command == "$sta/ssid=MyNet"


def test_build_helper_collapses_spaces_and_strips_comments():
    c = built("G1   X1  (a comment) Y2 ; trailing")
    # runs of spaces collapse to one, but the comment chars reset the "previous was a
    # space" flag, so the spaces around a removed comment both survive
    assert c.Command == "G1 X1  Y2 "
    assert num(c.X) == 1 and num(c.Y) == 2


def test_parenthesis_comment_suppresses_letters_inside():
    c = built("G0 (X99 move) X1")
    assert num(c.X) == 1
    assert c.Command == "G0  X1"


def test_semicolon_starts_comment_until_end_of_line():
    c = built("M3 S500;X10")
    assert c.X is None and num(c.S) == 500


def test_unparseable_number_stops_parsing_silently():
    c = built("G1 X1..2 Y3")
    # Decimal.Parse("1..2") throws inside BuildHelper; the exception is swallowed and
    # only the elements parsed before it are kept (see FINDINGS.md F-01)
    assert num(c.G) == 1 and c.X is None and c.Y is None
    assert c.JustBuilt


def test_repeated_letter_keeps_parsing_until_duplicate_key():
    c = built("G90 G1 X1")
    # Dictionary.Add throws on the second G: swallowed, the rest of the line is lost
    assert num(c.G) == 90 and c.X is None


def test_dollar_commands_are_not_parsed_into_elements():
    c = built("$J=G91X10F100")
    assert c.IsGrblCommand and c.X is None and c.G is None
    assert c.Command == "$J=G91X10F100"


def test_serial_data_strips_spaces_for_gcode_but_not_for_dollar_commands():
    assert GrblCommand("G1 X1 Y2").SerialData == "G1X1Y2\n"
    assert GrblCommand("$sta/ssid=My Net", 0, True).SerialData == "$sta/ssid=My Net\n"


def test_empty_line_is_empty():
    assert GrblCommand("   ").IsEmpty
    assert not GrblCommand("G0").IsEmpty


def test_build_and_delete_helper():
    c = GrblCommand("G0 X1")
    assert not c.JustBuilt
    c.BuildHelper()
    assert c.JustBuilt
    c.BuildHelper()  # second call is a no-op
    c.DeleteHelper()
    assert not c.JustBuilt


def test_constructor_from_elements_and_with_prefix_element():
    E = GrblCommand.Element
    els = System.Collections.Generic.List[E]()
    els.Add(E("X", System.Decimal(1.5)))
    els.Add(E("y", System.Decimal(-2)))
    c = GrblCommand(els)
    assert c.Command == "X1.5 Y-2"
    c2 = GrblCommand(E("G", System.Decimal(1)), GrblCommand("x3"))
    assert c2.Command == "G1 X3"


def test_element_implicit_conversion_equality_and_hash():
    E = GrblCommand.Element
    a = cu.scall(E, "op_Implicit", "X1.50")
    b = E("X", System.Decimal.Parse("1.50", System.Globalization.CultureInfo.InvariantCulture))
    assert str(a) == "X1.50"
    assert a.Equals(b) and a.GetHashCode() == b.GetHashCode()
    assert not a.Equals(E("Y", System.Decimal(1.5)))
    assert not a.Equals("X1.50")


def test_repeat_count_and_decoded_message():
    assert GrblCommand("G0", 0).GetDecodedMessage() == "G0"
    c = GrblCommand("G0 X1", 2)
    assert c.RepeatCount == 2
    assert c.GetDecodedMessage() == "G0 X1 (Retry 2)"
    assert str(c.ToString()) == "G0 X1"


def test_clone_shares_result_wrapper():
    c = GrblCommand("G0")
    k = c.Clone()
    k.SetResult("ok", False)
    # MemberwiseClone copies the reference to the private ResultWrapper, so the
    # result set on the clone is visible on the original (see FINDINGS.md F-02)
    assert c.Status == Status.ResponseGood


def test_time_offset_roundtrip():
    c = GrblCommand("G0")
    c.SetOffset(System.TimeSpan.FromSeconds(3))
    assert c.TimeOffset.TotalSeconds == 3


def test_dispose_and_clear_result():
    c = GrblCommand("G0")
    c.SetResult("ok", False)
    c.ClearResult()
    assert c.Status == Status.Queued
    c.Dispose()
    assert c.LinkedDisplayList is None


# ---------------------------------------------------------------- classification
@pytest.mark.parametrize(
    "line,linear,arc",
    [
        ("G1 X1", True, False),
        ("Y2", True, False),
        ("Z-1", True, False),
        ("G2 X1 Y1 I1 J0", False, True),
        ("G3 X1 R5", False, True),
        ("G92 X0 Y0", False, False),
        ("M3 S100", False, False),
        ("G0", False, False),
    ],
)
def test_movement_classification(line, linear, arc):
    c = built(line)
    assert c.IsLinearMovement == linear
    assert c.IsArcMovement == arc
    assert c.IsMovement == (linear or arc)


def test_set_wco_and_g_modes():
    assert built("G92 X0").IsSetWCO
    assert built("G4 P1").IsPause
    assert built("G90").IsAbsoluteCoord and not built("G90").IsRelativeCoord
    assert built("G91").IsRelativeCoord
    assert not built("X1").IsPause and not built("X1").IsAbsoluteCoord and not built("X1").IsRelativeCoord


def test_is_cw_uses_g2_g3_else_previous():
    assert built("G2 X1 I1").IsCW(False) is True
    assert built("G3 X1 I1").IsCW(True) is False
    assert built("X1 I1").IsCW(True) is True
    assert built("G1 X1").IsCW(False) is False


@pytest.mark.parametrize("line,m3,m4,m5", [("M3", 1, 0, 0), ("M4 S10", 0, 1, 0), ("M5", 0, 0, 1), ("G0", 0, 0, 0)])
def test_spindle_codes(line, m3, m4, m5):
    c = built(line)
    assert (c.IsM3, c.IsM4, c.IsM5) == (bool(m3), bool(m4), bool(m5))
    assert c.IsLaserON == bool(m3 or m4)
    assert c.IsLaserOFF == bool(m5)


def test_parameter_accessors():
    c = built("T1 S2 P3 X4 Y5 Z6 I7 J8 F9 R10")
    assert [num(getattr(c, k)) for k in "TSPXYZIJFR"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert c.M is None


@pytest.mark.parametrize("line,eeprom", [("$100=80", True), ("$$", False), ("$X", False), ("G10 L2", False)])
def test_eeprom_write_detection(line, eeprom):
    assert GrblCommand(line).IsWriteEEPROM == eeprom


# ---------------------------------------------------------------- status / result
def test_status_lifecycle():
    c = GrblCommand("G0")
    assert c.Status == Status.Queued and c.ImageIndex == 0
    cu.call(c, "SetSending")
    assert c.Status == Status.WaitingResponse and c.ImageIndex == 0
    c.SetResult(" ok \r", False)
    assert c.Status == Status.ResponseGood and c.ImageIndex == 1
    c.SetResult("error:20", False)
    assert c.Status == Status.ResponseBad and c.ImageIndex == 2
    c.SetResult("weird", False)
    assert c.Status == Status.InvalidResponse and c.ImageIndex == 2


def test_result_decoding_uses_error_csv():
    c = GrblCommand("G0")
    c.SetResult("error:1", True)
    assert c.GetResult(True, False) == "Expected command letter"
    assert c.GetResult(False, False) == "ERROR:1"
    assert c.GetToolTip(True).startswith("G-code words consist of a letter")
    assert c.GetToolTip(False) == ""


def test_result_unknown_error_code_falls_back_to_raw():
    c = GrblCommand("G0")
    c.SetResult("error:999", True)
    assert c.GetResult(True, False) == "ERROR:999"
    assert c.GetToolTip(True) == ""


def test_result_when_csv_lookup_throws():
    c = GrblCommand("G0")
    c.SetResult("error:1", True)
    saved = CSVD.Errors
    CSVD.Errors = None  # GetItem on null -> NullReferenceException, swallowed
    try:
        assert c.GetResult(True, False) == "ERROR:1"
        assert c.GetToolTip(True) == ""
    finally:
        CSVD.Errors = saved


def test_good_result_and_erroronly():
    c = GrblCommand("G0")
    c.SetResult("ok", True)
    assert c.GetResult(True, True) is None
    assert c.GetResult(True, False) == "OK"


def test_row_colors():
    c = GrblCommand("G0")
    assert c.LeftColor == ColorScheme.LogLeftCOMMAND
    assert c.RightColor == ColorScheme.LogRightOTHERS
    c.SetResult("ok", False)
    assert c.RightColor == ColorScheme.LogRightGOOD
    c.SetResult("error:1", False)
    assert c.RightColor == ColorScheme.LogRightBAD


# ---------------------------------------------------------------- GrblMessage
@pytest.mark.parametrize(
    "text,mtype,color",
    [
        ("$100=80.000", MT.Config, "LogLeftCONFIG"),
        ("Grbl 1.1f ['$' for help]", MT.Startup, "LogLeftSTARTUP"),
        ("ALARM:1", MT.Alarm, "LogLeftALARM"),
        ("<Idle|MPos:0,0,0>", MT.Position, "LogLeftPOSITION"),
        ("[MSG:Reset to continue]", MT.Feedback, "LogLeftFEEDBACK"),
        ("hello", MT.Others, "LogLeftOTHERS"),
    ],
)
def test_message_type_detection_and_color(text, mtype, color):
    m = GrblMessage(text, False)
    assert cu.get(m, "mType") == mtype
    assert m.LeftColor == getattr(ColorScheme, color)
    assert m.RightColor == System.Drawing.Color.Black
    assert m.ImageIndex == 3
    assert m.GetResult(True, False) is None


def test_message_warning_and_diagnostic_types():
    w = GrblMessage(" careful ", MT.Warning)
    d = GrblMessage("diag", MT.Diagnostic)
    assert w.GetDecodedMessage() == "careful" and w.GetNativeMessage() == "careful"
    assert w.ImageIndex == 4 and d.ImageIndex == 5
    assert w.LeftColor == ColorScheme.LogLeftOTHERS


def test_message_decodes_config_line_with_csv():
    m = GrblMessage("$110=500.000", True)
    assert m.GetDecodedMessage() == "$110=500.000 (X-axis maximum rate)"
    assert m.GetToolTip(True) == "X-axis maximum rate. Used as G0 rapid rate. [mm/min]"
    assert m.GetNativeMessage() == "$110=500.000"


def test_message_unknown_config_key_keeps_text():
    m = GrblMessage("$999=1", True)
    assert m.GetDecodedMessage() == "$999=1" and m.GetToolTip(True) is None


def test_message_decodes_alarm_with_csv():
    m = GrblMessage("ALARM:1", True)
    assert m.GetDecodedMessage() == "Hard limit"
    assert m.GetToolTip(True).startswith("Hard limit has been triggered")


def test_message_unknown_alarm_decodes_to_none():
    m = GrblMessage("ALARM:77", True)
    # brief lookup returns null and is assigned as the message (see FINDINGS.md F-03)
    assert m.GetDecodedMessage() is None


def test_message_decode_exception_is_swallowed():
    m = GrblMessage("$=1", True)  # Substring(1, -1) throws
    assert m.GetDecodedMessage() == "$=1"


# ---------------------------------------------------------------- CSVD
def V(major, minor, build="f", vendor=None, vendor_version=None, hal=False):
    return GrblCore.GrblVersionInfo(major, minor, build, vendor, vendor_version, hal)


@pytest.mark.parametrize(
    "version,setting_probe,expected",
    [
        (V(1, 1, vendor="Ortur Laser Master 3", hal=True), "481", "settings ortur hal"),
        (V(1, 1, vendor="Ortur Laser Master 2", vendor_version="171"), "41", "ortur 1.7"),
        (V(1, 1, vendor="Ortur Laser Master 2", vendor_version="150"), "41", "ortur 1.5"),
        (V(1, 1, vendor="Ortur Laser Master 2", vendor_version="140"), "41", "ortur 1.4"),
        (V(1, 1, vendor="NanoDuo"), "0", "nanoduo"),
        (V(0, 9, "j"), "0", "v0.9"),
    ],
)
def test_load_appropriate_csv_selects_resource(version, setting_probe, expected):
    CSVD.LoadAppropriateCSV(version)
    # each resource is a distinct CSV: verify by comparing against a fresh load
    names = {
        "settings ortur hal": "setting_codes.ortur.GrblHal.csv",
        "ortur 1.7": "setting_codes.ortur.v1.7.x.csv",
        "ortur 1.5": "setting_codes.ortur.v1.5.x.csv",
        "ortur 1.4": "setting_codes.ortur.v1.4.x.csv",
        "nanoduo": "setting_codes.longer.nanoduo.csv",
        "v0.9": "setting_codes.v0.9.csv",
    }
    ref = CsvDictionary("LaserGRBL.CSV." + names[expected], 3)
    assert CSVD.Settings.GetItem(setting_probe, 0) == ref.GetItem(setting_probe, 0)
    assert cu.get(CSVD.Settings, "mD").Count == cu.get(ref, "mD").Count


def test_load_appropriate_csv_alarm_and_error_variants():
    CSVD.LoadAppropriateCSV(V(1, 1, vendor="Ortur Laser Master 3", hal=True))
    hal_err = CsvDictionary("LaserGRBL.CSV.error_codes.ortur.GrblHal.csv", 2)
    assert cu.get(CSVD.Errors, "mD").Count == cu.get(hal_err, "mD").Count
    CSVD.LoadAppropriateCSV(V(1, 1, vendor="NanoDuo"))
    nd = CsvDictionary("LaserGRBL.CSV.alarm_codes.longer.nanoduo.csv", 2)
    assert cu.get(CSVD.Alarms, "mD").Count == cu.get(nd, "mD").Count
    CSVD.LoadAppropriateCSV(V(1, 1))
    std = CsvDictionary("LaserGRBL.CSV.error_codes.csv", 2)
    assert cu.get(CSVD.Errors, "mD").Count == cu.get(std, "mD").Count


def test_load_appropriate_csv_unknown_version_falls_back_to_v11():
    CSVD.LoadAppropriateCSV(V(2, 5))  # setting_codes.v2.5.csv does not exist
    ref = CsvDictionary("LaserGRBL.CSV.setting_codes.v1.1.csv", 3)
    assert cu.get(CSVD.Settings, "mD").Count == cu.get(ref, "mD").Count


def test_load_appropriate_csv_null_version_falls_back_everywhere():
    CSVD.LoadAppropriateCSV(None)  # NullReferenceException in every loader -> defaults
    assert CSVD.Errors.GetItem("1", 0) == "Expected command letter"
    assert CSVD.Alarms.GetItem("1", 0) == "Hard limit"


def test_constructor_from_empty_element_list():
    assert GrblCommand(System.Collections.Generic.List[GrblCommand.Element]()).Command == ""


def test_tooltip_for_good_result_is_empty():
    c = GrblCommand("G0")
    c.SetResult("ok", True)
    assert c.GetToolTip(True) == ""


@pytest.mark.parametrize("text", ["$X", "<Idle", "[MSG", "Idle>", "MSG]"])
def test_message_partial_markers_are_others(text):
    assert cu.get(GrblMessage(text, False), "mType") == MT.Others
