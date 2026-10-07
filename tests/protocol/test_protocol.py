"""Wire-level behaviour of the host against a Grbl 1.1 device on a serial line (PTY).

Only the HostAdapter API and the bytes the device received are used, so these
tests can run unchanged against a future Rust host.
"""

import pytest

from lasergrbl_harness.fake_grbl import FakeGrbl
from lasergrbl_harness.host import wait
from lasergrbl_harness.jobs import FOOTER, HEADER, job_lines, next_fits, settle, wire
from lasergrbl_harness.waiting import stays_true


# ---------------------------------------------------------------- connection
def test_connect_sends_soft_reset_then_status_query_then_reads_settings(host, pty, device):
    host.connect(pty.path)
    wait(lambda: host.connected and "$I" in device.lines, 10)
    assert device.realtime[0] == 0x18  # ctrl-x first
    assert device.realtime[1] == 0x3F  # then '?'
    assert device.lines[:2] == ["$$", "$I"]
    assert host.firmware_version == "1.1f"
    wait(lambda: host.status == "Idle", 5)


def test_connect_without_soft_reset_waits_for_the_board_banner(host, pty, device):
    host.set_option("reset_on_connect", False)
    host.set_option("query_machine_info", False)
    host.connect(pty.path)
    wait(lambda: 0x3F in device.realtime, 5)
    assert 0x18 not in device.realtime
    pty.announce()  # the board prints its banner (e.g. after a DTR reset)
    wait(lambda: host.firmware_version == "1.1f" and host.connected, 5)
    wait(lambda: "$$" in device.lines, 5)
    assert "$I" not in device.lines


def test_status_is_polled_periodically(connected, device):
    wait(lambda: device.realtime.count(0x3F) >= 3, 3, "status polling stopped")


def test_disconnect_closes_the_line(connected, device):
    connected.disconnect()
    assert not connected.connected and connected.status == "Disconnected"


# ---------------------------------------------------------------- streaming
def test_stream_sends_header_job_and_footer_in_order(connected, device, job):
    lines = job_lines(120)
    connected.load_gcode(job(lines))
    connected.run_job()
    wait(lambda: FOOTER in device.lines, 20, "job did not finish")
    assert device.lines == [HEADER] + [wire(x) for x in lines] + [FOOTER]
    wait(lambda: not connected.job_running, 5)


def test_stream_never_overflows_the_127_byte_rx_buffer(host, classic, job):
    device = classic
    device.set_auto_ack(False)
    lines = job_lines(60)  # 20-21 bytes each on the wire
    expected = [HEADER] + [wire(x) for x in lines]
    host.load_gcode(job(lines))
    host.run_job()
    while len(device.lines) < len(expected):
        # let the host fill the buffer as much as it can, then free one line
        wait(lambda: not next_fits(device, expected, 127), 5)
        device.release(1)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines == expected + [FOOTER]
    assert device.overflows == 0
    assert 127 - 21 < device.max_rx_used <= 127


def test_stream_uses_128_bytes_when_grbl_reports_it(connected, device, job):
    # Grbl 1.1 reports [OPT:V,15,128] (and Bf:..,128 when empty): the host adopts 128
    device.set_auto_ack(False)
    lines = job_lines(60)
    expected = [HEADER] + [wire(x) for x in lines]
    connected.load_gcode(job(lines))
    connected.run_job()
    while len(device.lines) < len(expected):
        wait(lambda: not next_fits(device, expected, 128), 5)
        device.release(1)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.overflows == 0 and device.max_rx_used <= 128


def test_stream_waits_when_rx_buffer_full(host, classic, job):
    device = classic
    device.set_auto_ack(False)
    lines = job_lines(40)
    expected = [HEADER] + [wire(x) for x in lines]
    host.load_gcode(job(lines))
    host.run_job()
    wait(lambda: not next_fits(device, expected, 127), 5)
    sent = len(device.lines)
    # nothing more may arrive while no "ok" is returned
    assert stays_true(lambda: len(device.lines) == sent, 0.5)
    # the first "ok" frees only the 4-byte header, too little for a 20-byte line:
    # still nothing is sent; the second one makes room
    device.release(1)
    assert stays_true(lambda: len(device.lines) == sent, 0.3)
    device.release(1)
    wait(lambda: len(device.lines) > sent, 5)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)


def test_synchronous_mode_keeps_one_line_in_flight(host, pty, device, job):
    host.set_option("streaming_mode", "Synchronous")
    host.connect(pty.path)
    settle(host, device)
    device.set_auto_ack(False)
    host.load_gcode(job(job_lines(10)))
    host.run_job()
    wait(lambda: device.pending_lines == 1, 5)
    assert stays_true(lambda: device.pending_lines == 1, 0.3)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)


# ---------------------------------------------------------------- pause / resume / reset
def test_feed_hold_pauses_and_cycle_start_resumes(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(30)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    connected.feed_hold()
    wait(lambda: 0x21 in device.realtime, 5)
    wait(lambda: connected.status == "Hold", 5)
    device.set_auto_ack(True)  # still holding: nothing executes
    executed = len(device.responses)
    assert stays_true(lambda: device.hold, 0.3)
    connected.resume()
    wait(lambda: 0x7E in device.realtime, 5)
    wait(lambda: FOOTER in device.lines, 10)
    assert len(device.responses) > executed


def test_soft_reset_mid_job_stops_streaming(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(80)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    connected.soft_reset()
    wait(lambda: device.resets >= 1, 5)
    after = len(device.lines)
    assert stays_true(lambda: len(device.lines) == after, 0.5)
    assert FOOTER not in device.lines
    assert not connected.job_running
    assert "ManualReset" not in connected.issues  # user actions are not reported as issues


def test_abort_job_flushes_and_turns_laser_off(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(80)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    connected.abort_job()
    device.set_auto_ack(True)
    wait(lambda: device.lines and device.lines[-1] == "M5", 5)
    assert FOOTER not in device.lines and not connected.job_running


# ---------------------------------------------------------------- errors and alarms
def test_error_mid_job_is_counted_and_streaming_continues(connected, device, job):
    lines = job_lines(20)
    device.error_rules = [(wire(lines[5]) + "$", 33)]
    connected.load_gcode(job(lines))
    connected.run_job()
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines.count(wire(lines[5])) == 1
    assert connected.job_errors == 1


def test_error_mid_job_is_retried_in_repeat_on_error_mode(host, pty, device, job):
    host.set_option("streaming_mode", "RepeatOnError")
    host.connect(pty.path)
    settle(host, device)
    lines = job_lines(8)
    device.error_rules = [(wire(lines[3]) + "$", 33)]
    host.load_gcode(job(lines))
    host.run_job()
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines.count(wire(lines[3])) == 4  # first try + 3 retries


def test_alarm_mid_job_is_reported(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(50)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    device.alarm_now(1)
    wait(lambda: "MachineAlarm" in connected.issues, 5)
    wait(lambda: connected.status == "Alarm", 5)
    device.set_auto_ack(True)


def test_unlock_and_home(connected, device):
    connected.write_settings({22: "1"})  # homing cycle enable, otherwise $H is not allowed
    connected.unlock()
    connected.home()
    wait(lambda: "$H" in device.lines, 5)
    assert device.lines[-2:] == ["$X", "$H"]


# ---------------------------------------------------------------- manual commands, jog, overrides, settings
def test_manual_command_is_sent_compressed(connected, device):
    connected.send_command("g1 x10 y5 f300")
    wait(lambda: "G1X10Y5F300" in device.lines, 5)


def test_jog_uses_dollar_j_relative(connected, device):
    connected.jog("NE", 2.5, 800)
    wait(lambda: device.lines, 5)
    assert device.lines[-1] == "$J=G91X2.5Y2.5F800"


def test_overrides_converge_to_targets(connected, device):
    connected.set_override_targets(130, 25, 80)
    wait(lambda: device.ov == [130, 25, 80], 10, f"overrides stuck at {device.ov}")
    assert {0x91, 0x97, 0x9B}.issubset(set(device.realtime))
    connected.set_override_targets(100, 100, 100)
    wait(lambda: device.ov == [100, 100, 100], 10)
    assert {0x90, 0x95, 0x99}.issubset(set(device.realtime))


def test_write_settings_sends_one_dollar_line_per_setting(connected, device):
    connected.write_settings({110: "4000", 111: "4500"})
    assert device.lines[-2:] == ["$110=4000", "$111=4500"]
    assert device.settings[110] == "4000" and device.settings[111] == "4500"


def test_host_uses_the_rx_buffer_size_reported_by_the_board(host, job):
    from lasergrbl_harness.links import PtyLink

    dev = FakeGrbl(rx_size=256, opt_line="[OPT:V,15,256]", report_buffer=False)
    link = PtyLink(dev)
    try:
        host.connect(link.path)
        wait(lambda: "$I" in dev.lines and dev.pending_lines == 0 and host.ready and host.status == "Idle", 10)
        dev.set_auto_ack(False)
        host.load_gcode(job(job_lines(40)))
        host.run_job()
        wait(lambda: dev.rx_used > 200, 5, "host did not use the larger buffer")
        dev.set_auto_ack(True)
        wait(lambda: FOOTER in dev.lines, 10)
        assert dev.overflows == 0 and dev.max_rx_used <= 256
    finally:
        link.close()
        host.close()
