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
