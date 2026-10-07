"""The tolerance used for the Rust host on ``platform_dependent`` cases."""

from lasergrbl_harness.tolerance import PIXEL_MAX_DELTA, pixel_difference, pixels_within_tolerance


def test_identical_and_close_bitmaps_pass():
    rows = ["FF000000 FF808080", "00000000 FFFFFFFF"]
    assert pixel_difference(rows, rows) == (0, 0.0)
    assert pixels_within_tolerance(rows, rows)
    close = ["FF020202 FF7E7E7E", "00000000 FFFFFFFF"]
    assert pixel_difference(close, rows) == (2, 12 / 16)
    assert pixels_within_tolerance(close, rows)


def test_far_or_different_size_bitmaps_fail():
    rows = ["FF000000 FF000000"]
    far = [f"FF{PIXEL_MAX_DELTA + 1:02X}0000 FF000000"]
    assert not pixels_within_tolerance(far, rows)
    # every channel a little off: the mean fails before the maximum
    assert not pixels_within_tolerance(["FB050505 FB050505"], rows)
    assert pixel_difference(["FF000000"], rows) is None
    assert not pixels_within_tolerance(["FF000000"], rows)
    assert not pixels_within_tolerance(None, rows)
    assert pixel_difference([], []) == (0, 0.0)


def test_burn_maps():
    from lasergrbl_harness.tolerance import _edges, burn_map, gcode_difference, gcode_within_tolerance

    a = ["M3 S0", "F1000", "G0 X0 Y0", "G1 X1 S500", "X2 S1000", "M5"]
    assert gcode_within_tolerance(a, a, 0.1)
    # the same burn written in more lines
    split = ["M3 S0", "F1000", "G0 X0 Y0", "G1 X0.5 S500", "X1 S500", "X2 S1000", "M5"]
    assert gcode_difference(split, a, 0.1) == (0.0, 0.0)
    # slightly different powers pass, very different fail
    assert gcode_within_tolerance(["M3 S0", "F1000", "G0 X0 Y0", "G1 X1 S510", "X2 S1000", "M5"], a, 0.1)
    assert not gcode_within_tolerance(["M3 S0", "F1000", "G0 X0 Y0", "G1 X1 S900", "X2 S1000", "M5"], a, 0.1)
    # different header
    assert not gcode_within_tolerance(["M4 S0"] + a[1:], a, 0.1)
    assert not gcode_within_tolerance(None, a, 0.1)
    assert _edges(["M3", "M5"]) == (["M3", "M5"], [])
    # on/off laser, relative moves, arcs, comments
    onoff = ["G91", "M3 S255", "G1 X1 (go)", "M5", "G90", "G2 X3 Y0 I1 J0 M3", "G3 X5 Y0 I1 J0"]
    cells = burn_map(onoff, 0.1, 255)
    # clockwise over the top, counter-clockwise under the bottom
    assert cells[(5, 0)] == 255 and (20, 9) in cells and (40, -10) in cells
    assert gcode_difference([], [], 0.1) == (0.0, 0.0)


def test_summaries():
    from lasergrbl_harness.tolerance import summary_within_tolerance

    s = {"count": 3, "estimated_time_s": 1.0, "drawing_range": [0, 0, 1, 1], "moving_range": [0, 0, 1, 1]}
    assert summary_within_tolerance({**s, "count": 9, "estimated_time_s": 1.04}, s, 0.1)
    assert not summary_within_tolerance({**s, "estimated_time_s": 1.2}, s, 0.1)
    assert not summary_within_tolerance({**s, "drawing_range": [0, 0, 1.3, 1]}, s, 0.1)
    assert not summary_within_tolerance({**s, "drawing_range": None}, s, 0.1)
    assert not summary_within_tolerance(None, s, 0.1)
