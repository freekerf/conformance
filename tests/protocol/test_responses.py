"""What the host makes of the board's replies: banners and vendors, status reports,
messages, alarms, holds, issues during jobs, buffer size, override stepping.

Like test_protocol.py, only the HostAdapter API and the device are used."""

import time

import pytest

from lasergrbl_harness.host import wait
from lasergrbl_harness.jobs import FOOTER, job_lines, wire
from lasergrbl_harness.waiting import stays_true

ORTUR = "Ortur Laser Master 3 Ready!\r\nOLF 182.\r\nGrbl 1.1f ['$' for help]"


# ---------------------------------------------------------------- banners and vendors
@pytest.mark.parametrize(
    "welcome,version,vendor",
    [
        ("Grbl 1.1h ['$' for help]", "1.1h", None),
        ("GrblHAL 1.1f ['$' or '$HELP' for help]", "1.1f", None),
        ("Grbl-Vigo:1.1f|Build:G-20170131-V3.0-20200720", "1.1f", "Grbl-Vigo"),
        (ORTUR, "1.1f", "Ortur Laser Master 3"),
        ("Aufero AL1 Ready!\r\nGrbl 1.1f ['$' for help]", "1.1f", "Aufero AL1"),
        ("[Machine:Longer Nano]\r\nGrbl 1.1f ['$' for help]", "1.1f", "Longer Nano"),
        ("SimpleLaser 1.1f ['$' for help]", "1.1f", "SimpleLaser"),
        ("FluidNC 3.7x", "3.7x", "FluidNC"),
    ],
    ids=["grbl", "grblhal", "vigo", "ortur", "aufero", "longer", "simplelaser", "unknown-firmware"],
)
def test_banner_sets_version_and_vendor(host, board, welcome, version, vendor):
    board(welcome=welcome, settle_host=False)
    wait(lambda: host.connected and host.firmware_version == version, 10)
    assert host.firmware_version == version and host.firmware_vendor == vendor


@pytest.mark.parametrize("welcome", ["Grbl x.yz", "GrblHAL bad", "Grbl-Vigo:x", "SimpleLaser zz", "Fw 99999999999.1a"])
def test_malformed_banner_sets_no_version(host, board, welcome):
    board(welcome=welcome, settle_host=False)
    wait(lambda: host.connected, 10)
    assert stays_true(lambda: host.firmware_version is None, 1.0)


def test_board_restart_during_a_job_is_an_unexpected_reset(connected, device, pty, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(40)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    pty.announce()  # the board prints its banner again: it restarted
    wait(lambda: "UnexpectedReset" in connected.issues, 5)
    assert not connected.job_running
    device.set_auto_ack(True)
    sent = len(device.lines)
    assert stays_true(lambda: len(device.lines) == sent and FOOTER not in device.lines, 0.5)


# ---------------------------------------------------------------- status reports
def test_status_report_positions_and_work_offset(connected, device):
    device.mpos, device.wco = [1.0, 2.0, 3.0], [0.5, 1.0, 0.0]
    wait(lambda: connected.machine_position == (1.0, 2.0, 3.0), 5)
    assert connected.work_offset == (0.5, 1.0, 0.0)


def test_status_report_with_wpos_is_converted_with_the_last_wco(host, board):
    device = board(report_wpos=True)
    device.mpos, device.wco = [11.0, 22.0, 3.0], [10.0, 20.0, 0.0]
    wait(lambda: host.machine_position == (11.0, 22.0, 3.0), 5)
    assert host.work_offset == (10.0, 20.0, 0.0)


def test_status_report_with_two_axes(connected, device):
    device.mpos = [1.0, 2.0]  # a two-axis board
    wait(lambda: connected.machine_position == (1.0, 2.0, 0.0), 5)


def test_status_report_without_a_known_version_is_read_by_its_shape(host, board):
    # no soft reset, no banner: the "|" report is read as Grbl 1.1
    host.set_option("reset_on_connect", False)
    device = board(send_welcome_on_open=False, settle_host=False)
    device.mpos = [4.0, 5.0, 6.0]
    wait(lambda: host.status == "Idle" and host.machine_position == (4.0, 5.0, 6.0), 5)
    assert host.firmware_version is None


def test_unknown_machine_state_is_ignored(connected, device):
    device.state, device.mpos = "Sleep", [9.0, 9.0, 9.0]
    assert stays_true(lambda: connected.status == "Idle" and connected.machine_position == (0, 0, 0), 1.0)


def test_legacy_status_reports_of_grbl_09(host, board):
    device = board(version="0.9j", legacy_status=True, settle_host=False)
    wait(lambda: host.firmware_version == "0.9j" and host.status == "Idle", 10)
    device.mpos, device.wco = [5.0, 6.0, 7.0], [4.0, 4.0, 4.0]
    wait(lambda: host.machine_position == (5.0, 6.0, 7.0), 5)
    assert host.work_offset == (4.0, 4.0, 4.0)


@pytest.mark.rust_divergence("DIV-015")
def test_pin_report_without_a_known_version_is_not_parsed(host, board):
    # no soft reset, no banner: the version is unknown; a "|" report with "Pin:" is
    # taken for Grbl 1.0c and read with the comma parser, which fails (F-15)
    host.set_option("reset_on_connect", False)
    board(send_welcome_on_open=False, extra_status=["Pin:XYZ"], settle_host=False)
    wait(lambda: host.status == "Connecting", 5)
    assert stays_true(lambda: host.status == "Connecting", 2.0)


def test_hold_requested_by_the_board_is_an_auto_hold(connected, device):
    device.hold_now()
    wait(lambda: connected.status == "AutoHold", 5)
    connected.resume()
    wait(lambda: 0x7E in device.realtime and connected.status == "Idle", 5)


def test_door_open_is_resumed_with_cycle_start(connected, device):
    device.receive(bytes([0x84]))  # the door switch opens
    wait(lambda: connected.status == "Door", 5)
    connected.resume()
    wait(lambda: 0x7E in device.realtime, 5)


def test_feed_hold_and_resume_are_not_sent_when_not_allowed(connected, device):
    connected.feed_hold()  # idle: nothing to hold
    connected.resume()  # not in hold
    assert stays_true(lambda: not {0x21, 0x7E} & set(device.realtime), 0.5)


@pytest.mark.rust_divergence("DIV-020")
def test_safety_door_sends_the_legacy_at_sign(connected, device):
    connected.safety_door()
    connected.send_command("G0 X1")
    wait(lambda: device.lines, 5)
    # '@' is the Grbl 0.9 door command; Grbl 1.1 takes it as a character of the next line (F-20)
    assert device.lines == ["@G0X1"] and 0x84 not in device.realtime


# ---------------------------------------------------------------- messages, alarms, oks
def test_ip_messages_are_recorded(connected, device):
    device.push("[MSG:Get IP 192.168.1.182]")
    wait(lambda: connected.detected_ip == "192.168.1.182", 5)
    device.push("[MSG:Connected with 10.0.0.7]")
    wait(lambda: connected.detected_ip == "10.0.0.7", 5)


def test_alarm_while_idle_is_not_an_issue(connected, device):
    device.alarm_now(2)
    wait(lambda: connected.status == "Alarm", 5)
    assert connected.issues == []


def test_ok_without_a_pending_line_is_ignored(host, classic, job):
    device = classic
    for _ in range(3):
        device.push("ok")  # nothing is pending: must not free buffer space
    device.set_auto_ack(False)
    lines = job_lines(40)
    host.load_gcode(job(lines))
    host.run_job()
    wait(lambda: len(device.lines) > 3, 5)
    assert stays_true(lambda: device.rx_used <= 127, 0.5)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.overflows == 0 and device.max_rx_used <= 127


def test_garbled_ok_still_acknowledges_the_line(host, board, job):
    device = board(ok_reply="xokx")
    host.load_gcode(job(job_lines(20)))
    host.run_job()
    wait(lambda: FOOTER in device.lines and not host.job_running, 10)
    assert host.job_errors == 0


def _broken_ok_acknowledges(host, device, line):
    device.set_auto_ack(False)
    host.send_command("$110=500")  # a settings write: nothing else is sent until it is answered
    host.send_command("G0 X1")
    wait(lambda: device.lines == ["$110=500"], 5)
    device.push(line)
    wait(lambda: device.lines == ["$110=500", "G0X1"], 5)
    device.set_auto_ack(True)


@pytest.mark.rust_divergence("DIV-051")
def test_any_message_containing_ok_acknowledges_a_line(connected, device):
    # the "broken ok" rule is "contains ok" (case-insensitive), checked before the
    # alarm and IP rules: a message such as [MSG:Look up] acknowledges the oldest
    # pending line as if it were its "ok" (F-51)
    _broken_ok_acknowledges(connected, device, "[MSG:Look up]")


@pytest.mark.rust_divergence("DIV-051")
def test_a_startup_line_report_acknowledges_a_line(connected, device):
    # Grbl reports an executed startup block ($N0=...) as ">G54G20:ok"; the ":ok" is
    # there so that senders do not count it (Grbl v1.1 interface), but the broken-ok
    # rule counts it (F-51)
    _broken_ok_acknowledges(connected, device, ">G54G20:ok")


def test_an_ok_merged_into_a_status_report_acknowledges_a_line(connected, device):
    # electrical noise: the "ok" lands inside a status report and the line is not a
    # status report any more (LaserGRBL discussion #1498, the reason for the rule)
    _broken_ok_acknowledges(connected, device, "<Idle|MPos:0.000,0.000,0.000|FS:0,0ok")


def test_lost_oks_are_recovered_when_the_board_reports_an_empty_buffer(connected, device, job):
    # noise ate the "ok" of every line in the buffer: the host waits for room that
    # never comes; after 10 s without activity, with the board reporting its RX
    # buffer empty (Bf), the host answers the pending lines itself and goes on
    lines = job_lines(40)
    device.drop_oks = 10**6
    connected.load_gcode(job(lines))
    connected.run_job()
    wait(lambda: len(device.lines) > 3, 5)
    wait(lambda: stays_true(lambda n=len(device.lines): len(device.lines) == n, 0.5), 5)  # stuck
    device.drop_oks = 0  # the line is clean again
    stuck_at = len(device.lines)
    assert stays_true(lambda: len(device.lines) == stuck_at, 5.0)
    wait(lambda: FOOTER in device.lines, 15)
    assert [ln for ln in device.lines if ln.startswith("G1")] == [wire(x) for x in lines]


def test_disconnect_by_the_user_during_a_job_is_not_an_issue(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(40)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    connected.disconnect()
    wait(lambda: not connected.connected, 10)
    assert connected.issues == [] and not connected.job_running
    assert connected.last_issue == "ManualDisconnect"


def test_no_status_for_too_long_during_a_job_is_reported(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(40)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    device.mute_status = True  # the board stops answering '?'
    wait(lambda: "StopResponding" in connected.issues, 15)


# ---------------------------------------------------------------- RX buffer size
@pytest.mark.parametrize(
    "kwargs,size",
    [
        ({"report_buffer": True, "opt_line": "[OPT:V,15]"}, 128),  # learnt from Bf: of the status
        ({"report_buffer": False, "opt_line": "[OPT:V,15]"}, 127),  # nothing advertised
        ({"report_buffer": False, "opt_line": "[OPT:V,abc,xyz]"}, 127),  # malformed
        ({"report_buffer": False, "error_rules": [(r"^\$I$", 3)]}, 127),  # $I rejected
        ({"report_buffer": False, "rx_size": 100, "opt_line": "[OPT:V,15,100]"}, 127),  # unknown size
        ({"report_buffer": True, "rx_size": 100, "opt_line": "[OPT:V,15]"}, 127),  # unknown size in Bf:
        ({"report_buffer": False, "rx_size": 255, "opt_line": "[OPT:V,15,255]"}, 255),
        ({"report_buffer": False, "rx_size": 1024, "opt_line": "[OPT:V,15,1024]"}, 1024),
        ({"report_buffer": False, "rx_size": 10240, "opt_line": "[OPT:V,15,10240]"}, 10240),
    ],
    ids=["bf-128", "none", "malformed-opt", "info-rejected", "opt-100", "bf-100", "opt-255", "opt-1024",
         "opt-10240"],
)
def test_rx_buffer_size_learnt_from_the_board(host, board, kwargs, size):
    board(**kwargs)
    wait(lambda: host.buffer_size == size, 3)
    assert stays_true(lambda: host.buffer_size == size, 0.5)


def test_rx_buffer_size_from_bf_without_machine_info_query(host, board):
    host.set_option("query_machine_info", False)
    device = board(settle_host=False)
    wait(lambda: "$$" in device.lines and host.ready and host.status == "Idle", 10)
    wait(lambda: host.buffer_size == 128, 3)
    assert "$I" not in device.lines


@pytest.mark.parametrize("delay,size", [(0.0, 128), (0.1, 128), (0.8, 127)], ids=["ok-first", "late-100ms", "late-800ms"])
def test_settings_and_info_replies_after_their_ok(host, board, delay, size):
    # some clones answer "ok" before the $$/$I data; data later than 500 ms is missed
    board(report_buffer=False, ok_first=True, data_delay=delay)
    time.sleep(delay + 0.6)  # let late data arrive (or be missed)
    assert host.buffer_size == size


# ---------------------------------------------------------------- overrides
def ov_bytes(device):
    return [b for b in device.realtime if 0x90 <= b <= 0x9D]


@pytest.mark.parametrize(
    "cur,target,sent",
    [
        ((100, 100, 100), (110, 100, 100), [0x91]),
        ((120, 100, 100), (100, 100, 100), [0x90]),
        ((120, 100, 100), (110, 100, 100), [0x92]),
        ((100, 100, 100), (105, 100, 100), [0x93] * 5),
        ((105, 100, 100), (101, 100, 100), [0x94] * 4),
        ((100, 100, 100), (100, 100, 130), [0x9A] * 3),
        ((100, 100, 130), (100, 100, 110), [0x9B] * 2),
        ((100, 100, 100), (100, 100, 102), [0x9C] * 2),
        ((100, 100, 102), (100, 100, 100), [0x99]),
        ((100, 100, 103), (100, 100, 101), [0x9D] * 2),
        ((100, 25, 100), (100, 100, 100), [0x95]),
        ((100, 100, 100), (100, 50, 100), [0x96]),
        ((100, 100, 100), (100, 25, 100), [0x97]),
        ((90, 50, 95), (100, 100, 100), [0x90, 0x99, 0x95]),
        ((100, 100, 100), (95, 100, 107), [0x94, 0x9C] * 5 + [0x9C] * 2),
    ],
)
def test_overrides_step_towards_the_targets(connected, device, cur, target, sent):
    device.mute_status = True
    time.sleep(0.3)  # let the reports already on the line reach the host
    device.ov = list(cur)
    connected.set_override_targets(*target)
    device.realtime.clear()
    device.mute_status = False
    wait(lambda: device.ov == list(target) or len(ov_bytes(device)) >= len(sent), 10)
    # one step per status report until the board reports the targets
    assert stays_true(lambda: ov_bytes(device) == sent, 1.0)


def test_overrides_are_not_pushed_back_after_a_soft_reset(connected, device):
    connected.set_override_targets(100, 100, 130)
    wait(lambda: device.ov == [100, 100, 130], 10)
    connected.soft_reset()  # the board restarts with 100 %; so do the host's targets
    wait(lambda: device.resets >= 1 and device.ov == [100, 100, 100], 5)
    device.realtime.clear()
    assert stays_true(lambda: ov_bytes(device) == [] and device.ov == [100, 100, 100], 1.5)
