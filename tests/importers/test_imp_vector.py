"""DXF reader errors and units, ArcFitter, BezierTools and the VectorDrawing model."""

import math

import clr
import System
import pytest

clr.AddReference("WindowsBase")
from System.Windows import Point  # noqa: E402

import LaserGRBL  # noqa: E402
from LaserGRBL import GrblFile, Settings  # noqa: E402
from LaserGRBL.SvgConverter import ArcFitter, DxfImportException, DxfReader, VectorDrawing, VectorPath, VectorSegment  # noqa: E402

from lasergrbl_harness import clr_util as cu  # noqa: E402
from lasergrbl_harness import importers as im  # noqa: E402

DXF = im.INPUTS / "dxf"
BezierTools = cu.clr_type(GrblFile).Assembly.GetType("LaserGRBL.SvgConverter.BezierTools")
Strings = cu.clr_type(GrblFile).Assembly.GetType("LaserGRBL.Strings")  # internal resource class


# ------------------------------------------------------------ DxfReader

def test_binary_dxf_is_rejected():
    with pytest.raises(DxfImportException) as e:
        DxfReader.Read(str(DXF / "binary.dxf"), 0.01)
    assert str(e.value.Message) == str(cu.sget(Strings, "DxfBinaryNotSupported"))


def test_dxf_without_drawable_entities_is_rejected():
    with pytest.raises(DxfImportException) as e:
        DxfReader.Read(str(DXF / "empty.dxf"), 0.01)
    assert str(e.value.Message) == str(cu.sget(Strings, "DxfNoEntities"))


def test_file_shorter_than_the_binary_signature(tmp_path):
    p = tmp_path / "tiny.dxf"
    p.write_text("0\n")
    with pytest.raises(DxfImportException):
        DxfReader.Read(str(p), 0.01)


def test_malformed_group_code_throws_format_exception(tmp_path):
    p = tmp_path / "bad.dxf"
    p.write_text("0\nSECTION\n2\nENTITIES\n\nLINE\n0\nENDSEC\n0\nEOF\n")
    with pytest.raises(System.FormatException):
        DxfReader.Read(str(p), 0.01)


@pytest.mark.parametrize("code,mm", [(0, 1), (1, 25.4), (2, 304.8), (3, 1), (4, 1), (5, 10), (6, 1000), (7, 1),
                                     (8, 0.0000254), (9, 0.0254), (10, 914.4), (11, 1), (13, 0.001), (14, 100), (99, 1)])
def test_insunits_to_mm(code, mm):
    assert cu.scall(DxfReader, "UnitsToMM", code) == pytest.approx(mm)


def test_default_spline_tolerance_comes_from_the_setting():
    path = str(DXF / "curves.dxf")
    Settings.SetObject(ArcFitter.ToleranceSetting, System.Double(0.0))
    lines_only = DxfReader.Read(path)
    assert not any(s.IsArc for p in lines_only.Paths for s in p.Segments if p.Color == "#00FF00")
    with_arcs = DxfReader.Read(path, ArcFitter.DefaultTolerance)
    assert any(s.IsArc for p in with_arcs.Paths for s in p.Segments if p.Color == "#00FF00")


# ------------------------------------------------------------ ArcFitter

def pts(*xy):
    l = System.Collections.Generic.List[Point]()
    for x, y in xy:
        l.Add(Point(float(x), float(y)))
    return l


def circle_pts(cx, cy, r, a0, a1, n):
    return pts(*[(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)])


def describe(segs):
    out = []
    for s in segs:
        e = (round(s.End.X, 6), round(s.End.Y, 6))
        out.append(("arc", e, (round(s.Center.X, 6), round(s.Center.Y, 6)), bool(s.CCW)) if s.IsArc else ("line", e))
    return out


def test_fit_needs_two_points():
    assert describe(ArcFitter.Fit(pts(), 0.01)) == []
    assert describe(ArcFitter.Fit(pts((1, 1)), 0.01)) == []


def test_fit_straight_points_to_one_line():
    assert describe(ArcFitter.Fit(pts((0, 0), (1, 0), (2, 0), (3, 0), (4, 0)), 0.01)) == [("line", (4, 0))]


def test_fit_counterclockwise_and_clockwise_arcs():
    ccw = describe(ArcFitter.Fit(circle_pts(0, 0, 10, 0, math.pi / 2, 16), 0.01))
    assert ccw == [("arc", (0, 10), (0, 0), True)]
    cw = describe(ArcFitter.Fit(circle_pts(0, 0, 10, math.pi / 2, 0, 16), 0.01))
    assert cw == [("arc", (10, 0), (0, 0), False)]


def test_fit_points_going_back_on_a_line_are_lines():
    """Collinear but not monotonic: no line through them and no circle (d == 0)."""
    assert describe(ArcFitter.Fit(pts((0, 0), (2, 0), (1, 0)), 0.01)) == [("line", (2, 0)), ("line", (1, 0))]


def test_fit_rejects_circles_larger_than_10_m():
    assert describe(ArcFitter.Fit(pts((0, 0), (100, 0.2), (200, 0)), 0.01)) == [("line", (100, 0.2)), ("line", (200, 0))]


def test_fit_never_makes_a_full_circle():
    segs = describe(ArcFitter.Fit(circle_pts(0, 0, 5, 0, 2 * math.pi - 1e-7, 64), 0.001))
    # the longest arc stops before closing the circle; the last tiny piece is a line
    assert segs[0][0] == "arc" and segs[0][1] != (5.0, 0.0)
    assert segs[-1] == ("line", (5.0, -1e-06))


def test_fit_rejects_points_out_of_order_along_the_circle():
    a = [0, 0.4, 0.2, 0.6, 0.8]
    got = describe(ArcFitter.Fit(pts(*[(10 * math.cos(t), 10 * math.sin(t)) for t in a]), 0.001))
    assert len(got) > 1


def test_fit_closed_loop_samples():
    """A range whose first and last points coincide: the line test projects with t = 0."""
    got = describe(ArcFitter.Fit(pts((0, 0), (0.001, 0), (0, 0)), 0.01))
    assert got == [("line", (0, 0))]


# ------------------------------------------------------------ BezierTools

def flatten(points, error=0.01, max_sub=20):
    res = cu.scall(BezierTools, "FlattenTo", pts(*points), error, max_sub)
    return [(round(p.X, 6), round(p.Y, 6)) for p in res]


def test_flatten_emits_the_control_points_of_flat_curves():
    """A sub-curve that is flat enough is emitted as its 4 control points (not only
    its end points): the polyline goes through off-curve control points."""
    assert flatten([(0, 0), (1, 0), (2, 0), (3, 0)]) == [(0, 0), (1, 0), (2, 0), (3, 0)]
    # flatness is sqrt(triangle area) < error, not a distance: a 1 um wiggle over 3 mm
    # (sqrt(0.0015) = 0.039) is not flat for error 0.01 and gets subdivided
    assert len(flatten([(0, 0), (1, 0.001), (2, -0.001), (3, 0)])) > 4


def test_flatten_curve_subdivides_until_flat():
    got = flatten([(0, 0), (0, 10), (10, 10), (10, 0)], error=0.1)
    assert got[0] == (0, 0) and got[-1] == (10, 0) and len(got) > 10
    coarse = flatten([(0, 0), (0, 10), (10, 10), (10, 0)], error=5)
    assert len(coarse) < len(got)


def test_flatten_stops_at_max_subdivisions():
    assert flatten([(0, 0), (0, 10), (10, 10), (10, 0)], error=1e-9, max_sub=0) == [(0, 0), (0, 10), (10, 10), (10, 0)]


def test_flatten_concatenates_curves_sharing_end_points():
    got = flatten([(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0), (7, 0)])
    # two cubic curves (0-3, 3-6); the trailing point that does not complete a curve is dropped
    assert got == [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (6, 0)]


# ------------------------------------------------------------ VectorDrawing

def test_path_end_is_start_without_segments():
    p = VectorPath("#000000", Point(1, 2))
    assert (p.End.X, p.End.Y) == (1, 2)


def test_tiny_arc_polyline_uses_45_degree_steps():
    p = VectorPath("#000000", Point(0.001, 0))
    p.Segments.Add(VectorSegment.Arc(Point(-0.001, 0), Point(0, 0), True))
    assert len(list(p.ToPolyline(0.01))) == 5  # half turn in 4 steps of pi/4


def test_sweep_directions_never_full_turn():
    s = VectorSegment.Arc(Point(1, 0), Point(0, 0), True)
    assert s.Sweep(Point(1, 0)) == pytest.approx(2 * math.pi)
    s.CCW = False
    assert s.Sweep(Point(1, 0)) == pytest.approx(-2 * math.pi)
    assert VectorSegment.Line(Point(3, 4)).IsArc is False


def test_empty_drawing_has_no_bounds_and_is_not_moved():
    d = VectorDrawing()
    ok, a, b, c, e = d.GetBounds(0.0, 0.0, 0.0, 0.0)
    assert ok is False
    d.MoveToOrigin()
    assert list(d.Colors()) == []


def test_drawing_colors_in_order_of_first_appearance():
    d = VectorDrawing()
    for c in ["#00FF00", "#000000", "#00FF00", "#FF0000"]:
        d.Paths.Add(VectorPath(c, Point(0, 0)))
    assert [str(c) for c in d.Colors()] == ["#00FF00", "#000000", "#FF0000"]
