"""GrblFile raster helpers: filling predicates, Line2Line edge cases, path ordering
(ParallelOptimizePaths / OptimizePaths) and ImageTransform corner cases."""

import System
import pytest

import LaserGRBL
from LaserGRBL import GrblFile
from LaserGRBL.RasterConverter import ImageProcessor, ImageTransform
from CsPotrace import Curve, CurveKind, dPoint

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness import importers as im

Direction = ImageProcessor.Direction

RASTER = {"Horizontal", "Vertical", "Diagonal"}
VECTOR = {"NewHorizontal", "NewVertical", "NewDiagonal", "NewReverseDiagonal", "NewGrid", "NewDiagonalGrid",
          "NewCross", "NewDiagonalCross", "NewSquares", "NewZigZag", "NewHilbert", "NewInsetFilling"}
SLOW = {"NewCross", "NewDiagonalCross", "NewSquares"}


def test_filling_predicates_truth_table():
    names = [str(n) for n in System.Enum.GetNames(cu.clr_type(Direction))]
    assert set(names) == {"None"} | RASTER | VECTOR
    for name in names:
        d = getattr(Direction, name)
        assert GrblFile.RasterFilling(d) == (name in RASTER), name
        assert GrblFile.VectorFilling(d) == (name in VECTOR), name
        assert GrblFile.TimeConsumingFilling(d) == (name in SLOW), name


def conf(**kw):
    c = GrblFile.L2LConf()
    for k, v in {**im.L2L_DEFAULTS, **kw}.items():
        if k == "dir":
            v = getattr(Direction, v)
        elif k == "firmwareType":
            v = getattr(LaserGRBL.Firmware, v)
        setattr(c, k, v)
    return c


def cmds(f):
    return [str(c.Command) for c in f]


def test_l2l_with_a_vector_direction_emits_only_header_and_footer():
    f = GrblFile()
    f.LoadImageL2L(im.make_bitmap({"pixels": ["00 FF", "FF 00"]}), "x", conf(dir="NewHorizontal"), False, None)
    assert cmds(f) == ["G0 X0 Y0 F1000", "M3 S0", "M5"]


def test_l2l_append_keeps_the_previous_commands():
    f = GrblFile()
    f.LoadImageL2L(im.make_bitmap({"pixels": ["00"]}), "a", conf(), False, None)
    first = cmds(f)
    f.LoadImageL2L(im.make_bitmap({"pixels": ["00"]}), "b", conf(oX=5.0), True, None)
    assert cmds(f)[: len(first)] == first
    assert cmds(f)[len(first)] == "G0 X5 Y0 F1000"


def test_l2l_flips_the_bitmap_it_is_given():
    """LoadImageL2L calls RotateFlip(FlipY) on the caller's Bitmap (side effect)."""
    bmp = im.make_bitmap({"pixels": ["00", "FF"]})
    GrblFile().LoadImageL2L(bmp, "x", conf(), False, None)
    assert im.dump_bitmap(bmp) == ["FFFFFFFF", "FF000000"]


# ------------------------------------------------------------ path ordering

def paths_at(xs):
    lst = System.Collections.Generic.List[System.Collections.Generic.List[Curve]]()
    for x in xs:
        a, b = dPoint(float(x), 0.0), dPoint(float(x), 1.0)
        one = System.Collections.Generic.List[Curve]()
        one.Add(Curve(CurveKind.Line, a, a, b, b))
        lst.Add(one)
    return lst


def xs_of(lst):
    return [int(round(p[0].A.X)) for p in lst]


def test_parallel_optimize_paths_returns_null_and_single_lists_unchanged():
    assert cu.scall(GrblFile, "ParallelOptimizePaths", None, 0.0) is None
    one = paths_at([7])
    assert cu.scall(GrblFile, "ParallelOptimizePaths", one, 0.0).Equals(one)
    assert cu.scall(GrblFile, "OptimizePaths", one, 0.0).Equals(one)


def test_optimize_paths_is_greedy_nearest_neighbour_from_the_path_nearest_zero():
    got = cu.scall(GrblFile, "ParallelOptimizePaths", paths_at([9, 3, 5, 20, 4]), 0.0)
    assert xs_of(got) == [3, 4, 5, 9, 20]


def test_parallel_optimize_paths_optimizes_blocks_of_2048_independently():
    n = 2050  # two blocks of 1025 paths, ordered on two tasks and concatenated
    xs = [(k * 7919) % n for k in range(n)]
    got = xs_of(cu.scall(GrblFile, "ParallelOptimizePaths", paths_at(xs), 0.0))
    first, second = sorted(xs[:1025]), sorted(xs[1025:])
    # each block restarts from its own path nearest to zero: the block boundary is visible
    assert got == first + second
    assert got != sorted(xs)


# ------------------------------------------------------------ ImageTransform

def test_grayscale_failure_returns_null():
    """draw_adjusted_image swallows every exception and returns null."""
    assert ImageTransform.GrayScale(None, 1, 1, 1, 0, 1, ImageTransform.Formula.SimpleAverage) is None


def test_random_dithering_keeps_black_and_white_and_outputs_only_pure_colors():
    bmp = im.make_bitmap({"pixels": ["00 FF 80 40", "C0 00 FF 20"]})
    out = im.dump_bitmap(ImageTransform.DitherImage(bmp, ImageTransform.DitheringMode.Random))
    toks = " ".join(out).split()
    assert set(toks) <= {"FF000000", "FFFFFFFF"}
    assert toks[0] == "FF000000" and toks[1] == "FFFFFFFF" and toks[5] == "FF000000" and toks[6] == "FFFFFFFF"


def test_unknown_dithering_mode_falls_back_to_floyd_steinberg():
    img = {"pixels": ["10 30 50 70 90 B0 D0 F0"] * 3}
    fs = im.dump_bitmap(ImageTransform.DitherImage(im.make_bitmap(img), ImageTransform.DitheringMode.FloydSteinberg))
    odd = System.Enum.ToObject(cu.clr_type(ImageTransform.DitheringMode), 99)
    assert im.dump_bitmap(ImageTransform.DitherImage(im.make_bitmap(img), odd)) == fs


def test_error_diffusion_never_reaches_first_row_or_column():
    """ErrorDiffusionDithering checks offsetX > 0 and offsetY > 0: no error is ever
    diffused into row 0 or column 0, so a uniform dark-gray first row is all black
    (FINDINGS)."""
    img = {"pixels": ["60 60 60 60 60 60"] * 3}
    out = im.dump_bitmap(ImageTransform.DitherImage(im.make_bitmap(img), ImageTransform.DitheringMode.FloydSteinberg))
    assert out[0] == " ".join(["FF000000"] * 6)
    assert all(row.split()[0] == "FF000000" for row in out)
    assert "FFFFFFFF" in out[1] or "FFFFFFFF" in out[2]


def test_direct_bitmap_get_set_pixel():
    db = ImageTransform.DirectBitmap(2, 1)
    db.SetPixel(1, 0, System.Drawing.Color.FromArgb(255, 1, 2, 3))
    c = db.GetPixel(1, 0)
    assert (c.A, c.R, c.G, c.B) == (255, 1, 2, 3)
    assert (db.Width, db.Height) == (2, 1)


def test_l2l_flips_bitmaps_drawn_with_graphics_too():
    """The bitmaps the raster pipeline hands to LoadImageL2L come out of
    ImageTransform (drawn with a Graphics). libgdiplus ignores pure flips on those;
    the harness shim (native/lgshim.c) makes them flip as on Windows."""
    src = im.make_bitmap({"pixels": ["00 00", "FF FF"]})
    bmp = ImageTransform.Threshold(src, 0.5, True)
    GrblFile().LoadImageL2L(bmp, "x", conf(), False, None)
    assert im.dump_bitmap(bmp) == ["FFFFFFFF FFFFFFFF", "FF000000 FF000000"]
