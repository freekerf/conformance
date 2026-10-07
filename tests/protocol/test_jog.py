"""Jogging on the wire: $J= for Grbl 1.1, plain G-code for Grbl 0.9, jog to a
position (soft limits), continuous jog, and the zeroing/homing buttons.

Like test_protocol.py, only the HostAdapter API and the device are used."""

import pytest

from lasergrbl_harness.fake_grbl import FakeGrbl
from lasergrbl_harness.host import wait
from lasergrbl_harness.jobs import FOOTER, job_lines
from lasergrbl_harness.waiting import stays_true


@pytest.mark.parametrize(
    "direction,expected",
    [
        ("N", "$J=G91Y10.0F1000"), ("S", "$J=G91Y-10.0F1000"), ("E", "$J=G91X10.0F1000"),
        ("W", "$J=G91X-10.0F1000"), ("NE", "$J=G91X10.0Y10.0F1000"), ("NW", "$J=G91X-10.0Y10.0F1000"),
        ("SE", "$J=G91X10.0Y-10.0F1000"), ("SW", "$J=G91X-10.0Y-10.0F1000"),
        ("Zup", "$J=G91Z10.0F1000"), ("Zdown", "$J=G91Z-10.0F1000"), ("Home", "$J=G90X0Y0F1000"),
    ],
)
def test_jog_direction(connected, device, direction, expected):
    connected.jog(direction, 10, 1000)
    wait(lambda: device.lines, 5)
    assert device.lines == [expected]


def test_jog_fractional_feed(connected, device):
    connected.jog("E", 1, 1234.5)
    wait(lambda: device.lines, 5)
    assert device.lines == ["$J=G91X1.0F1234.5"]


@pytest.mark.rust_divergence("DIV-022")
def test_jog_step_is_rounded_to_one_decimal(connected, device):
    connected.jog("E", 0.25, 1000)
    connected.jog("E", 0.04, 1000)
    wait(lambda: len(device.lines) == 2, 5)
    # "0.0" format: 0.25 -> 0.3 and 0.04 -> 0.0, a zero-length jog (F-22)
    assert device.lines == ["$J=G91X0.3F1000", "$J=G91X0.0F1000"]


def test_jog_to_a_position_uses_two_decimals(connected, device):
    connected.jog_to(12.345, 6.7, 1000)
    connected.jog_to(1, 2, 300)
    wait(lambda: len(device.lines) == 2, 5)
    assert device.lines == ["$J=G90X12.35Y6.70F1000", "$J=G90X1.00Y2.00F300"]


def test_jog_to_a_position_is_clamped_by_the_soft_limits(connected, device):
    connected.write_settings({20: "1", 130: "300", 131: "200"})
    device.wco = [10.0, 20.0, 0.0]
    wait(lambda: connected.work_offset == (10.0, 20.0, 0.0), 5)
    device.lines.clear()
    connected.jog_to(500, -50, 1000)
    wait(lambda: device.lines, 5)
    # the machine area in work coordinates: [-WCO, table size - WCO]
    assert device.lines == ["$J=G90X290.00Y-20.00F1000"]


def test_jog_is_not_sent_during_a_job(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(30)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    connected.jog("E", 10, 1000)
    connected.jog_to(1, 1, 1000)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)
    assert not any(ln.startswith("$J=") for ln in device.lines)


# ---------------------------------------------------------------- Grbl 0.9
@pytest.fixture
def v09(host, board):
    return board(version="0.9j", legacy_status=True, settle_host=False)


def settle_v09(host, device):
    wait(lambda: host.firmware_version == "0.9j" and "$$" in device.lines, 10)
    # connect-time queries done: the wire stays quiet and the host is ready
    wait(lambda: stays_true(lambda n=len(device.lines): len(device.lines) == n and device.pending_lines == 0
                            and host.ready and host.status == "Idle", 0.7), 10)
    device.lines.clear()


def test_jog_on_grbl_09_is_a_relative_move(host, v09):
    settle_v09(host, v09)
    host.jog("NE", 1, 500)
    host.jog("Zdown", 1, 500)
    wait(lambda: len(v09.lines) == 6, 5)
    assert v09.lines == ["G91", "G1X1.0Y1.0F500", "G90", "G91", "G1Z-1.0F500", "G90"]


def test_jog_home_and_jog_to_on_grbl_09(host, v09):
    settle_v09(host, v09)
    host.jog("Home", 1, 500)
    host.jog_to(3, 4, 500)
    wait(lambda: len(v09.lines) == 4, 5)
    assert v09.lines == ["G90", "G1X0Y0F500", "G90", "G1X3.00Y4.00F500"]


def test_continuous_jog_is_not_used_on_grbl_09(host, board):
    host.set_option("continuous_jog", True)
    device = board(version="0.9j", legacy_status=True, settle_host=False)
    settle_v09(host, device)
    host.jog("E", 1, 500)
    host.jog_abort()  # nothing to cancel on 0.9
    wait(lambda: len(device.lines) == 3, 5)
    assert device.lines == ["G91", "G1X1.0F500", "G90"] and 0x85 not in device.realtime


# ---------------------------------------------------------------- continuous jog
@pytest.fixture
def continuous(host, board):
    host.set_option("continuous_jog", True)
    return board()


@pytest.mark.parametrize(
    "direction,expected",
    [
        ("N", "$J=G53Y300.0F7"), ("S", "$J=G53Y0.0F7"), ("E", "$J=G53X400.0F7"), ("W", "$J=G53X0.0F7"),
        ("NE", "$J=G53X400.0Y300.0F7"), ("SW", "$J=G53X0.0Y0.0F7"), ("NW", "$J=G53X0.0Y300.0F7"),
        ("SE", "$J=G53X400.0Y0.0F7"), ("Home", "$J=G90X0Y0F7"),
    ],
)
def test_continuous_jog_goes_to_the_edge_of_the_table(host, continuous, direction, expected):
    # the board's table is $130=400 x $131=300: the jog targets its edge in machine coordinates
    host.jog(direction, 10, 7)
    wait(lambda: continuous.lines, 5)
    assert continuous.lines == [expected]


def test_continuous_jog_z_is_a_step_jog(host, continuous):
    host.jog("Zup", 10, 1000)
    wait(lambda: continuous.lines, 5)
    assert continuous.lines == ["$J=G91Z10.0F1000"]


def test_continuous_jog_new_target_cancels_the_previous_one(host, continuous):
    host.jog("E", 10, 100)
    wait(lambda: continuous.lines, 5)
    host.jog_to(7, 8, 1000)
    wait(lambda: len(continuous.lines) == 2, 5)
    assert continuous.lines == ["$J=G53X400.0F100", "$J=G90X7.00Y8.00F1000"]
    assert [b for b in continuous.realtime if b != 0x3F] == [0x85]


def test_continuous_jog_stop_cancels_once(host, continuous):
    host.jog("E", 10, 100)
    wait(lambda: continuous.lines, 5)
    host.jog_abort()
    wait(lambda: 0x85 in continuous.realtime, 5)
    host.jog_abort()  # nothing left to cancel
    assert stays_true(lambda: continuous.realtime.count(0x85) == 1, 0.5)


def test_jog_stop_without_continuous_jog_sends_nothing(connected, device):
    connected.jog("E", 10, 100)
    wait(lambda: device.lines, 5)
    connected.jog_abort()
    assert stays_true(lambda: 0x85 not in device.realtime, 0.5)


def test_continuous_jog_waits_for_the_pending_lines(host, continuous):
    continuous.set_auto_ack(False)
    host.send_command("G0 X1")
    wait(lambda: continuous.lines == ["G0X1"], 5)
    host.jog("E", 10, 100)
    assert stays_true(lambda: continuous.lines == ["G0X1"], 0.5)
    continuous.set_auto_ack(True)
    wait(lambda: continuous.lines == ["G0X1", "$J=G53X400.0F100"], 5)


FULL_TABLE = FakeGrbl().settings  # $130=400, $131=300


@pytest.mark.parametrize(
    "board_kwargs,expected",
    [
        ({"error_rules": [(r"^\$\$$", 9)]}, "$J=G53X300.0Y200.0F100"),  # no table: 300 x 200
        ({"settings": {0: "10", 110: "500"}}, "$J=G53X300.0Y200.0F100"),  # partial table: defaults
        ({"settings": {**FULL_TABLE, 130: "99999999", 131: "0.000"}}, "$J=G53X2000000.0Y1.0F100"),  # clamped
        ({"settings": {**FULL_TABLE, 130: "500.5 mm", 131: "250.000 (y max travel)"}},
         "$J=G53X500.5Y250.0F100"),  # the number found in the text
        ({"settings": {**FULL_TABLE, 130: "none"}}, "$J=G53X300.0Y300.0F100"),  # no number: the default
    ],
    ids=["rejected", "partial", "clamped", "text", "unparseable"],
)
def test_continuous_jog_edges_from_the_settings_table(host, board, board_kwargs, expected):
    host.set_option("continuous_jog", True)
    device = board(**board_kwargs)
    host.jog("NE", 10, 100)
    wait(lambda: device.lines, 5)
    assert device.lines == [expected]


def test_continuous_jog_edges_follow_a_settings_refresh(host, continuous):
    continuous.settings[130], continuous.settings[131] = "123.000", "45.000"
    host.refresh_settings()
    continuous.lines.clear()
    host.jog("NE", 10, 100)
    wait(lambda: continuous.lines, 5)
    assert continuous.lines == ["$J=G53X123.0Y45.0F100"]


# ---------------------------------------------------------------- zero and homing buttons
def test_set_zero_only_away_from_the_work_zero(connected, device):
    connected.set_zero()  # already at the work zero: nothing to do
    assert stays_true(lambda: device.lines == [], 0.5)
    connected.send_command("G0 X5")
    wait(lambda: connected.machine_position == (5.0, 0.0, 0.0), 5)
    connected.set_zero()
    wait(lambda: len(device.lines) == 2, 5)
    assert device.lines == ["G0X5", "G92X0Y0Z0"]


def test_settings_write_failure_is_reported_and_the_rest_is_written(connected, device):
    with pytest.raises(Exception):
        connected.write_settings({111: "800", 555: "1"})  # $555 does not exist
    assert device.settings[111] == "800" and "$555=1" in device.lines


@pytest.mark.rust_divergence("DIV-016")
def test_settings_written_before_any_read_are_forgotten(host, board):
    # $$ rejected: there is no table; the host applies a written value to a
    # throw-away default table (F-16), so soft limits stay off for jog_to
    device = board(error_rules=[(r"^\$\$$", 9)])
    host.write_settings({20: "1", 130: "300", 131: "200"})
    device.lines.clear()
    host.jog_to(500, -50, 1000)
    wait(lambda: device.lines, 5)
    assert device.lines == ["$J=G90X500.00Y-50.00F1000"]


def test_rejected_settings_write_leaves_the_table_unchanged(connected, device):
    device.error_rules = [(r"^\$20=", 9)]
    with pytest.raises(Exception):
        connected.write_settings({20: "1"})  # soft limits stay off
    device.error_rules = []
    device.lines.clear()
    connected.jog_to(500, -50, 1000)
    wait(lambda: device.lines, 5)
    assert device.lines == ["$J=G90X500.00Y-50.00F1000"]


def test_home_is_not_sent_when_homing_is_disabled(connected, device):
    connected.home()  # the board has $22=0
    assert stays_true(lambda: device.lines == [], 0.5)
