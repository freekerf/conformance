"""GrblFile.LoadImagePotrace (vectorize) edge cases: Potrace options, append, the
bitmap side effect, events and the in-use guard. The traced outputs are golden cases
(fixtures/importers/cases/potrace_*.json)."""

import System
import pytest

import LaserGRBL
from LaserGRBL import GrblFile
from LaserGRBL.RasterConverter import ImageProcessor
from CsPotrace import Potrace

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness import importers as im
from LaserGRBLTests import GrblFileEvents

SQUARE = {"ascii": ["......", ".##...", ".##...", "......"]}


def conf(**kw):
    c = GrblFile.L2LConf()
    for k, v in {**im.L2L_DEFAULTS, "dir": "None", **kw}.items():
        if k == "dir":
            v = getattr(ImageProcessor.Direction, v)
        elif k == "firmwareType":
            v = getattr(LaserGRBL.Firmware, v)
        setattr(c, k, v)
    return c


def potrace(f, bmp, spot=None, smooth=None, opt=None, fast=False, append=False, **kw):
    f.LoadImagePotrace(bmp, "x", spot is not None, int(spot or 0), smooth is not None, System.Decimal(float(smooth or 0)),
                       opt is not None, System.Decimal(float(opt or 0)), fast, conf(**kw), append, None)


def cmds(f):
    return [str(c.Command) for c in f]


@pytest.fixture(autouse=True)
def restore_potrace_statics():
    saved = (Potrace.turdsize, Potrace.alphamax, Potrace.opttolerance, Potrace.curveoptimizing)
    yield
    Potrace.turdsize, Potrace.alphamax, Potrace.opttolerance, Potrace.curveoptimizing = saved


def test_disabled_options_set_potrace_defaults():
    """Unchecked options are not "off": spot removal falls back to turdsize 2 and
    optimization to tolerance 0.2 (with curve optimization disabled); smoothing off
    is alphamax 0 (every vertex a corner)."""
    potrace(GrblFile(), im.make_bitmap(SQUARE))
    assert (Potrace.turdsize, Potrace.alphamax, Potrace.opttolerance, Potrace.curveoptimizing) == (2, 0.0, 0.2, False)


def test_enabled_options_are_copied_to_the_potrace_statics():
    potrace(GrblFile(), im.make_bitmap(SQUARE), spot=7, smooth=1.25, opt=0.5)
    assert (Potrace.turdsize, Potrace.alphamax, Potrace.opttolerance, Potrace.curveoptimizing) == (7, 1.25, 0.5, True)


def test_white_image_emits_only_laser_on_and_off():
    f = GrblFile()
    potrace(f, im.make_bitmap({"ascii": ["...", "..."]}))
    assert cmds(f) == ["M3 S0", "F1000", "M5"]


def test_spot_removal_drops_shapes_up_to_the_turd_size():
    f = GrblFile()
    potrace(f, im.make_bitmap(SQUARE), spot=4)  # the 2x2 square has area 4
    assert cmds(f) == ["M3 S0", "F1000", "M5"]
    potrace(f, im.make_bitmap(SQUARE), spot=3)
    assert len(cmds(f)) > 3


def test_append_keeps_the_previous_commands():
    f = GrblFile()
    potrace(f, im.make_bitmap(SQUARE))
    first = cmds(f)
    potrace(f, im.make_bitmap(SQUARE), append=True, oX=5.0)
    assert cmds(f)[: len(first)] == first and len(cmds(f)) == 2 * len(first)


def test_flips_the_bitmap_it_is_given():
    """Like LoadImageL2L, LoadImagePotrace calls RotateFlip(FlipY) on the caller's Bitmap."""
    bmp = im.make_bitmap({"ascii": ["#.", ".."]})
    potrace(GrblFile(), bmp)
    assert im.dump_bitmap(bmp) == ["FFFFFFFF FFFFFFFF", "FF000000 FFFFFFFF"]


def test_raises_loading_and_loaded_once():
    f = GrblFile()
    ev = GrblFileEvents(f)
    potrace(f, im.make_bitmap(SQUARE))
    assert (ev.Loading, ev.Loaded) == (1, 1)


def test_in_use_file_shows_a_message_box_and_is_not_loaded():
    """CheckInUse() (with MessageBox) guards the load; headless the MessageBox throws."""
    f = GrblFile()
    cu.set(f, "InUse", True)
    with pytest.raises(Exception):
        potrace(f, im.make_bitmap(SQUARE))
    assert f.Count == 0


def test_borders_are_reversed_without_fast_optimization():
    """Potrace lists outer borders before inner ones; without "optimize fast" the list
    is reversed so holes are cut before the outline around them."""
    ring = {"ascii": ["........", ".######.", ".#....#.", ".#....#.", ".######.", "........"]}
    f = GrblFile()
    potrace(f, im.make_bitmap(ring))
    g0 = [c for c in cmds(f) if c.startswith("G0")]
    assert len(g0) == 2
    # the inner border (first) starts inside the outer one
    inner_y, outer_y = (float(c.split("Y")[1]) for c in g0)
    assert inner_y > outer_y


def test_raster_filling_sets_vectorfilling_on_the_callers_conf():
    """The raster filling inside LoadImagePotrace runs Line2Line with
    c.vectorfilling = true, written into the caller's L2LConf (FINDINGS)."""
    c = conf(dir="Horizontal")
    assert c.vectorfilling is False
    GrblFile().LoadImagePotrace(im.make_bitmap(SQUARE), "x", False, 0, False, System.Decimal(0), False,
                                System.Decimal(0), False, c, False, None)
    assert c.vectorfilling is True
