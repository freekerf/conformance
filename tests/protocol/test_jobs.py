"""Jobs on the wire: buffer edge cases, header/footer/passes custom code, passes,
resume from a position, custom buttons and their expressions.

Like test_protocol.py, only the HostAdapter API and the device are used."""

import pytest

from lasergrbl_harness.fake_grbl import FakeGrbl
from lasergrbl_harness.host import wait
from lasergrbl_harness.jobs import FOOTER, HEADER, PASSES, job_lines, wire
from lasergrbl_harness.waiting import stays_true


# ---------------------------------------------------------------- buffer edge cases
def test_line_that_exactly_fills_the_rx_buffer_is_sent(host, classic, job):
    device = classic
    full = "G1X" + "1" * 123  # 127 bytes with the newline
    device.set_auto_ack(False)
    host.load_gcode(job([full]))
    host.run_job()
    wait(lambda: device.lines == [HEADER], 5)
    assert stays_true(lambda: device.lines == [HEADER], 0.3)  # 4 + 127 bytes do not fit
    device.release(1)
    wait(lambda: device.lines == [HEADER, full], 5)
    assert device.rx_used == 127 and device.overflows == 0
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 5)


def test_line_bigger_than_the_rx_buffer_is_never_sent(host, classic, job):
    device = classic
    too_big = "G1X" + "1" * 124  # 128 bytes with the newline
    host.load_gcode(job([too_big, "G1 X1"]))
    host.run_job()
    wait(lambda: device.lines == [HEADER], 5)
    # the job stays stuck on that line: nothing after it is ever streamed
    assert stays_true(lambda: device.lines == [HEADER] and host.job_running, 1.0)
    host.abort_job()
    wait(lambda: device.lines[-1:] == ["M5"], 5)
    assert too_big not in device.lines


def test_settings_write_is_sent_alone(connected, device):
    # a $N=V line goes to the EEPROM: nothing else is sent until it is answered
    device.set_auto_ack(False)
    connected.send_command("$110=500")
    connected.send_command("G0 X1")
    wait(lambda: device.lines == ["$110=500"], 5)
    assert stays_true(lambda: device.lines == ["$110=500"], 0.5)
    device.release(1)
    wait(lambda: device.lines == ["$110=500", "G0X1"], 5)
    device.set_auto_ack(True)


# ---------------------------------------------------------------- header, footer, passes
def test_custom_header_and_footer_with_expressions_and_immediates(host, board, job):
    host.set_option("custom_header", "M3 S[$30/2]\n0x85\n\nG0 X[left] Y[bottom]")
    host.set_option("custom_footer", "M5\n!")
    device = board()
    host.load_gcode(job(["G0 X5 Y6", "M3 S10", "G1 X15 Y26 F100"]))
    host.run_job()
    wait(lambda: device.lines[-1:] == ["M5"], 10)
    # $30 comes from the board ($30=1000), left/bottom from the drawing (5, 6)
    assert device.lines == ["M3S500.000", "G0X5.000Y6.000", "G0X5Y6", "M3S10", "G1X15Y26F100", "M5"]
    wait(lambda: 0x21 in device.realtime, 5)  # '!' of the footer: sent at once
    assert 0x85 in device.realtime  # 0x85 of the header
    assert device.realtime.index(0x85) < device.realtime.index(0x21)


def test_passes_repeat_the_program_with_the_passes_code(connected, device, job):
    connected.load_gcode(job(["G1 X1 F100"]))
    connected.run_job(passes=2)
    wait(lambda: FOOTER in device.lines, 10)
    # the default passes code is four comment-only lines, streamed as empty lines (F-17)
    assert device.lines == [HEADER, "G1X1F100", *PASSES, "G1X1F100", FOOTER]
    wait(lambda: not connected.job_running, 5)


def test_custom_passes_code_runs_between_passes(host, board, job):
    host.set_option("custom_passes", "G91\nG0 Z-1\n\nG90")
    device = board()
    host.load_gcode(job(["G1 X1 F100"]))
    host.run_job(passes=3)
    wait(lambda: FOOTER in device.lines, 10)
    passes = ["G91", "G0Z-1", "G90"]
    assert device.lines == [HEADER, "G1X1F100", *passes, "G1X1F100", *passes, "G1X1F100", FOOTER]


def test_passes_run_once_in_check_mode(connected, device, job):
    connected.send_command("$C")
    wait(lambda: connected.status == "Check", 5)
    device.lines.clear()
    connected.load_gcode(job(["G1 X1 F100"]))
    connected.run_job(passes=3)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines == [HEADER, "G1X1F100", FOOTER]


def test_run_with_homing_sends_dollar_h_before_the_header(connected, device, job):
    connected.load_gcode(job(["G1 X1 F100"]))
    connected.run_job(homing=True)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines == ["$H", HEADER, "G1X1F100", FOOTER]


def test_run_without_a_program_sends_nothing(connected, device):
    connected.run_job()
    assert stays_true(lambda: device.lines == [] and not connected.job_running, 0.5)


def test_run_is_ignored_while_manual_commands_are_queued(connected, device, job):
    # the board acknowledges nothing: most manual lines wait in the host's queue
    device.set_auto_ack(False)
    manual = [f"G0 X{i}" for i in range(40)]
    for line in manual:
        connected.send_command(line)
    wait(lambda: len(device.lines) > 3, 5)
    connected.load_gcode(job(["G1 X1 F100"]))
    connected.run_job()  # a job needs an empty queue
    device.set_auto_ack(True)
    wait(lambda: len(device.lines) == len(manual), 10)
    assert device.lines == [wire(x) for x in manual]
    assert stays_true(lambda: len(device.lines) == len(manual) and not connected.job_running, 0.5)


def test_loading_a_file_replaces_the_previous_one(connected, device, job):
    connected.load_gcode(job(["G1 X1 F100", "G1 X2"], "a.nc"))
    connected.load_gcode(job(["G1 X3 F100"], "b.nc"))
    connected.run_job()
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines == [HEADER, "G1X3F100", FOOTER]


def test_abort_without_a_job_sends_nothing(connected, device):
    connected.abort_job()
    assert stays_true(lambda: device.lines == [], 0.5)


# ---------------------------------------------------------------- resume from a position
def test_resume_from_a_position_rebuilds_position_power_and_modes(connected, device, job):
    connected.load_gcode(job(["G21", "G1 X10 Y5 F600 S300", "M3", "X20", "G0 X30", "G1 Y40"]))
    connected.resume_job(3)
    wait(lambda: FOOTER in device.lines, 10)
    # no header; G21/G20 are not tracked as a modal group (F-18); the footer follows
    assert device.lines == ["G90", "M5G0X10Y5Z0F600S300", "M3", "G1X20", "G0X30", "G1Y40", FOOTER]


def test_resume_gives_the_first_move_its_motion_mode(connected, device, job):
    connected.load_gcode(job(["M3 S100", "G1 X1 F100", "X2", "X3"]))
    connected.resume_job(2)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines == ["G90", "M5G0X1Y0Z0F100S100", "M3", "G1X2", "X3", FOOTER]


@pytest.mark.rust_divergence("DIV-019")
def test_resume_without_settled_modal_groups_sends_an_empty_line(connected, device, job):
    connected.load_gcode(job(["G1 X1 F100", "X2", "X3"]))
    connected.resume_job(1)
    wait(lambda: FOOTER in device.lines, 10)
    # an empty "settled modal groups" command is queued anyway (F-19)
    assert device.lines == ["G90", "M5G0X1Y0Z0F100S0", "", "G1X2", "X3", FOOTER]


def test_resume_beyond_the_end_moves_to_the_last_position(connected, device, job):
    connected.load_gcode(job(["G0 X1"]))
    connected.resume_job(5)
    wait(lambda: FOOTER in device.lines, 10)
    assert device.lines[:2] == ["G90", "M5G0X1Y0Z0F0S0"]


def test_resume_with_homing_restores_the_work_offset_of_the_interrupted_job(connected, device, job):
    device.mpos, device.wco = [15.0, 5.0, 0.0], [5.0, 0.0, 0.0]
    wait(lambda: connected.work_offset == (5.0, 0.0, 0.0), 5)
    connected.load_gcode(job(["M3 S100", "G1 X10 F100", "G1 X20"]))
    device.set_auto_ack(False)
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    wait(lambda: device.realtime.count(0x3F) >= 2, 5)  # a status report seen while in the job
    connected.soft_reset()  # interrupted: the last WCO of the job is remembered
    wait(lambda: device.resets >= 1 and not connected.job_running and connected.status == "Idle", 10)
    device.set_auto_ack(True)
    device.lines.clear()
    connected.resume_job(2, homing=True, set_wco=True)
    wait(lambda: FOOTER in device.lines, 10)
    # after homing the position is 0: the work offset is restored as 0 - WCO
    assert device.lines == ["$H", "G92X-5Y0Z0", "G90", "M5G0X10Y0Z0F100S100", "M3", "G1X20", FOOTER]


# ---------------------------------------------------------------- custom code (buttons)
def test_custom_code_sends_immediates_at_once_and_queues_the_rest(connected, device):
    device.set_auto_ack(False)
    before = len(device.realtime)
    connected.custom_code("~\n0x9e\n0xZZ\nm3 s1 ; text\n$H")
    wait(lambda: 0x9E in device.realtime[before:], 5)
    assert [b for b in device.realtime[before:] if b != 0x3F] == [0x7E, 0x9E]
    device.set_auto_ack(True)
    wait(lambda: "$H" in device.lines, 5)
    # "0xZZ" is not a byte: sent as text; comments are removed when sending
    assert device.lines == ["0xZZ", "m3s1", "$H"]


def test_custom_code_expressions_see_the_drawing_the_board_and_its_settings(connected, device, job):
    device.mpos, device.wco = [3.0, 4.0, 5.0], [1.0, 2.0, 3.0]
    wait(lambda: connected.machine_position == (3.0, 4.0, 5.0), 5)
    connected.load_gcode(job(["G0 X10 Y20", "M3 S100", "G1 X30 Y50 F100"]))
    connected.custom_code("G0 X[left] Y[bottom]\nG0 X[right] Y[top]\nG0 X[width] Y[height]\n"
                          "G0 X[$130] Y[$131/3]\nG0 X[WCO.X] Z[MPos.Z]\nG0 X[nope+]")
    wait(lambda: len(device.lines) == 6, 5)
    assert device.lines == ["G0X10.000Y20.000", "G0X30.000Y50.000", "G0X20.000Y30.000",
                            "G0X400.000Y100.000", "G0X1.000Z5.000",
                            "G0X[nope+]"]  # an expression that does not evaluate is kept as text


def test_custom_code_expressions_see_the_jog_step_and_speed(host, board):
    host.set_option("jog_step", 2.5)
    host.set_option("jog_speed", 1200)
    device = board()
    host.custom_code("G1 X[jogstep*2] F[jogspeed]")
    wait(lambda: device.lines, 5)
    assert device.lines == ["G1X5.000F1200.000"]


def test_custom_code_expressions_without_settings_or_drawing(host, board):
    # $$ rejected: no table, $30 defaults to 1000; no program: the drawing is all 0
    device = board(error_rules=[(r"^\$\$$", 9)])
    host.custom_code("M3 S[$30] X[left] Y[top+1]")
    wait(lambda: device.lines, 5)
    assert device.lines == ["M3S1000.000X0.000Y1.000"]


@pytest.mark.rust_divergence("DIV-101")
def test_custom_code_wpos_variables_are_the_machine_position(connected, device):
    device.mpos, device.wco = [3.0, 4.0, 5.0], [1.0, 2.0, 3.0]
    wait(lambda: connected.machine_position == (3.0, 4.0, 5.0), 5)
    connected.custom_code("G0 X[WPos.X] Y[WPos.Y]")
    wait(lambda: device.lines, 5)
    assert device.lines == ["G0X3.000Y4.000"]


# ---------------------------------------------------------------- refusals and lost jobs
@pytest.mark.rust_divergence("DIV-024")
def test_write_settings_is_silently_skipped_during_a_job(connected, device, job):
    device.set_auto_ack(False)
    connected.load_gcode(job(job_lines(30)))
    connected.run_job()
    wait(lambda: connected.status == "Run", 5)
    connected.write_settings({110: "1"})  # no error, nothing queued (F-24)
    device.set_auto_ack(True)
    wait(lambda: FOOTER in device.lines, 10)
    assert "$110=1" not in device.lines


@pytest.mark.rust_divergence("DIV-030")
def test_job_started_during_the_connect_time_settings_read_is_cut_short(host, pty, device, job):
    # The board answers "ok" first and the settings 0.3 s later. While the host
    # collects them its queue pointers point to a private queue (F-30): a job started
    # then goes there, and its sent lines count as replies to $$, so the collection
    # ends early; the lines not sent yet are dropped when the pointers are restored.
    # Depending on thread timing the job then ends as if complete (footer sent) or
    # stays "in program" forever; either way only a prefix of it reached the board.
    device.ok_first, device.data_delay = True, 0.3
    lines = job_lines(200)
    host.load_gcode(job(lines))
    host.connect(pty.path)
    wait(lambda: "$$" in device.lines and host.status == "Idle", 10)
    host.run_job()
    accepted = host.job_running  # the host takes the job while it reads the settings
    wait(lambda: "$I" in device.lines and host.ready, 10)
    wait(lambda: stays_true(lambda n=len(device.lines): len(device.lines) == n, 1.0), 15)
    streamed = [ln for ln in device.lines if ln.startswith("G1")]
    assert accepted
    assert len(streamed) < len(lines) and streamed == [wire(x) for x in lines[:len(streamed)]]
    assert host.job_errors == 0
    ended = FOOTER in device.lines and not host.job_running
    stuck = FOOTER not in device.lines and host.job_running
    assert ended or stuck


# ---------------------------------------------------------------- auto cooling
def test_auto_cooling_holds_the_job_and_resumes_it(host, board, job):
    host.set_option("auto_cooling", (1, 1))  # 1 s of laser, 1 s of rest
    device = board()
    device.set_auto_ack(False)  # the job lasts as long as the test wants
    host.load_gcode(job(job_lines(60)))
    host.run_job()
    wait(lambda: host.status == "Run", 5)
    wait(lambda: 0x21 in device.realtime, 5)  # hold after 1 s of job time
    wait(lambda: host.status == "Cooling", 5)
    wait(lambda: 0x7E in device.realtime, 5)  # resume after 1 s of rest
    assert device.realtime.index(0x21) < device.realtime.index(0x7E)
    device.set_auto_ack(True)
    host.abort_job()


def test_auto_cooling_needs_laser_mode(host, board, job):
    host.set_option("auto_cooling", (1, 1))
    settings = dict(FakeGrbl().settings)
    settings[32] = "0"  # laser mode off
    device = board(settings=settings)
    device.set_auto_ack(False)
    host.load_gcode(job(job_lines(60)))
    host.run_job()
    wait(lambda: host.status == "Run", 5)
    assert stays_true(lambda: 0x21 not in device.realtime, 2.5)
    device.set_auto_ack(True)
    host.abort_job()
