"""Firmware variants on the wire: Smoothieware, Marlin and VigoWork hosts against a
Grbl-like device (the fake answers M114 for Marlin; Vigo's own reports are not modelled).

Like test_protocol.py, only the HostAdapter API and the device are used."""

from lasergrbl_harness.host import wait
from lasergrbl_harness.jobs import FOOTER, HEADER, job_lines, wire
from lasergrbl_harness.waiting import stays_true


def test_smoothie_connects_without_soft_reset_and_streams_one_line_at_a_time(host, pty, device, job):
    host.set_option("firmware", "Smoothie")
    host.connect(pty.path)
    wait(lambda: host.connected and host.status == "Idle", 10)
    # no ctrl-x: an empty line, then the status query
    assert bytes(device.raw[:2]) == b"\n?" and 0x18 not in device.realtime
    wait(lambda: host.ready and device.pending_lines == 0, 10)
    device.lines.clear()
    device.set_auto_ack(False)
    lines = job_lines(5)
    host.load_gcode(job(lines))
    host.run_job()
    wait(lambda: device.pending_lines == 1, 5)
    assert stays_true(lambda: device.pending_lines == 1, 0.3)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines == [HEADER] + [wire(x) for x in lines] + [FOOTER]


def test_smoothie_soft_reset_is_the_reset_command(host, pty, device):
    host.set_option("firmware", "Smoothie")
    host.connect(pty.path)
    wait(lambda: host.connected and host.ready and host.status == "Idle", 10)
    device.lines.clear()
    host.unlock()  # Smoothie has no unlock
    host.soft_reset()
    wait(lambda: device.lines, 5)
    assert device.lines == ["reset"] and 0x18 not in device.realtime


def test_marlin_polls_the_position_with_m114(host, pty, device):
    host.set_option("firmware", "Marlin")
    host.connect(pty.path)
    wait(lambda: device.lines.count("M114") >= 2, 10)
    wait(lambda: host.connected and host.status == "Idle", 10)
    # no soft reset, no '?', no settings or info query
    assert not {0x18, 0x3F} & set(device.realtime)
    assert set(device.lines) == {"M114"}


def test_vigo_queries_the_status_with_0x88(host, pty, device):
    host.set_option("firmware", "VigoWork")
    host.connect(pty.path)
    wait(lambda: 0x88 in device.realtime, 10)
    assert 0x3F not in device.realtime
