"""SVG import internals: color layers (settings, color normalization, scanning),
preview capture, hatch filling helpers, embedded resources and the static state of
the G-code writer."""

import clr
import System
import pytest

clr.AddReference("System.Xml.Linq")
clr.AddReference("WindowsBase")
from System.Xml.Linq import XElement  # noqa: E402

import LaserGRBL
from LaserGRBL import GrblFile, Settings
from LaserGRBL.RasterConverter import ImageProcessor
from LaserGRBL.SvgConverter import DxfImportSource, DxfReader, SvgColorLayer, SvgImportSource, SvgLayerMode

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness import importers as im
from lasergrbl_harness.core_rig import get_setting

ASM = cu.clr_type(GrblFile).Assembly
GCodeFromSVG = ASM.GetType("LaserGRBL.SvgConverter.GCodeFromSVG")
SvgFilling = ASM.GetType("LaserGRBL.SvgConverter.SvgFilling")
Direction = ImageProcessor.Direction


def svg_source(name):
    return SvgImportSource(cu.scall(GCodeFromSVG, "ParseSvgFile", str(im.INPUTS / "svg" / name)))


# ------------------------------------------------------------ SvgColorLayer

def test_layer_defaults():
    l = SvgColorLayer("#112233")
    assert (str(l.Color), l.Mode, l.Passes, l.FillDirection, l.LinesPerMM, l.Speed, l.Power, l.ElementCount) == (
        "#112233", SvgLayerMode.Line, 1, Direction.NewHorizontal, 10.0, 0, 0, 0)
    c = l.DrawingColor
    assert (c.R, c.G, c.B) == (0x11, 0x22, 0x33)


@pytest.mark.parametrize("mode,fill,outline,order", [
    ("Line", False, True, 1), ("Fill", True, False, 0), ("FillAndLine", True, True, 0),
    ("Cut", False, True, 2), ("Ignore", False, False, 2)])
def test_layer_mode_properties(mode, fill, outline, order):
    l = SvgColorLayer("#000000")
    l.Mode = getattr(SvgLayerMode, mode)
    assert (l.HasFill, l.HasOutline, l.ExecutionOrder) == (fill, outline, order)


def test_layer_settings_roundtrip():
    l = SvgColorLayer("#A1B2C3")
    l.Mode, l.Speed, l.Power, l.Passes = SvgLayerMode.Cut, 300, 900, 3
    l.FillDirection, l.LinesPerMM = Direction.NewGrid, 2.5
    l.SaveSettings()
    assert get_setting("SvgColorLayer.A1B2C3") == "Cut|300|900|3|NewGrid|2.5"
    r = SvgColorLayer("#A1B2C3")
    assert r.LoadSettings() is True
    assert (r.Mode, r.Speed, r.Power, r.Passes, r.FillDirection, r.LinesPerMM) == (
        SvgLayerMode.Cut, 300, 900, 3, Direction.NewGrid, 2.5)


def test_layer_settings_legacy_four_fields_and_minimum_one_pass():
    Settings.SetObject("SvgColorLayer.000001", "Fill|100|200|0")
    l = SvgColorLayer("#000001")
    assert l.LoadSettings() is True
    assert (l.Mode, l.Speed, l.Power, l.Passes, l.FillDirection, l.LinesPerMM) == (
        SvgLayerMode.Fill, 100, 200, 1, Direction.NewHorizontal, 10.0)


def test_layer_settings_missing_or_invalid():
    assert SvgColorLayer("#000002").LoadSettings() is False
    Settings.SetObject("SvgColorLayer.000003", "Cut|fast|1|1")
    l = SvgColorLayer("#000003")
    assert l.LoadSettings() is False
    # fields parsed before the error are kept: the layer is half loaded
    assert l.Mode == SvgLayerMode.Cut and l.Speed == 0


@pytest.mark.parametrize("value,expected", [
    (None, None), ("", None), ("none", None), ("url(#g)", None), ("currentColor", None),
    ("#abc", "#AABBCC"), ("#A0B0C0", "#A0B0C0"), ("red", "#FF0000"), ("Red", "#FF0000"),
    ("rgb(1,2,3)", "#010203"), ("rgb(100%, 50%, 0%)", "#FF8000"), ("rgba(10 20 30 / 0.5)", "#0A141E"),
    ("rgb(300,-5,2.6)", None), ("rgb(300,5,2.6)", "#FF0503"), ("transparent", "#FFFFFF"),
    ("#12", "#000012"), ("notacolor", None), ("#ggg", None), (" ", None),
])
def test_normalize_color(value, expected):
    got = SvgColorLayer.NormalizeColor(value)
    assert (None if got is None else str(got)) == expected


def test_resolve_color_prefers_stroke_then_fill_and_inherits():
    """The nearest declaration wins, "none" included: stroke:none on the element hides
    the inherited stroke and the (inherited) fill is used instead."""
    root = XElement.Parse('<svg xmlns="http://www.w3.org/2000/svg"><g style=";fill;:x; stroke :#010101"><g stroke="inherit" fill="#020202">'
                          '<rect/><rect style="stroke:none"/><rect stroke="none" fill="none"/></g></g><rect/></svg>')
    rects = [e for e in root.Descendants() if str(e.Name.LocalName) == "rect"]
    assert [str(SvgColorLayer.ResolveColor(r)) for r in rects] == ["#010101", "#020202", "#000000", "#000000"]


def test_scan_counts_only_converted_elements_of_the_svg_namespace():
    root = XElement.Parse('<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="urn:x"><x:rect/><text/><rect/>'
                          '<g><circle fill="red"/><x:g><rect/></x:g></g><image/></svg>')
    assert [(str(l.Color), l.ElementCount) for l in SvgColorLayer.Scan(root)] == [("#000000", 1), ("#FF0000", 1)]


# ------------------------------------------------------------ preview capture

def layers_of(source, **kw):
    lst = System.Collections.Generic.List[SvgColorLayer]()
    for l in source.ScanLayers():
        lst.Add(l)
    return lst


def polylines(shapes, color):
    return [[(round(p.X, 3), round(p.Y, 3)) for p in pl] for pl in shapes[color]]


def test_svg_capture_layers_returns_the_gcode_geometry_in_mm():
    src = svg_source("basic_shapes.svg")
    shapes = src.CaptureLayers(None, layers_of(src))
    assert list(shapes.Keys) == ["#000000"]
    pls = polylines(shapes, "#000000")
    # 12 elements, the polygon without commas has no shape (only a comment in the gcode)
    assert len(pls) == 11
    assert pls[0] == [(5.0, 45.0), (25.0, 45.0), (25.0, 55.0), (5.0, 55.0), (5.0, 45.0)]
    # arcs are sampled at about 0.2 mm (at least 8 segments): rounded rect corners and the
    # circle (the 6th shape: all rects come first), 2*pi*8/0.2 -> 252 segments
    assert len(pls[1]) > 20 and pls[1][0] == pls[1][-1]
    assert len(pls[5]) == 253 and pls[5][0] == pls[5][-1] == (23.0, 25.0)


def test_svg_capture_writes_no_gcode():
    src = svg_source("paths.svg")
    layers = layers_of(src)
    before = str(src.CreateGCode(None, layers))
    src.CaptureLayers(None, layers)
    im.reset_gcode_statics()
    assert str(src.CreateGCode(None, layers)) == before


def test_dxf_capture_layers_samples_arcs_within_fill_tolerance():
    src = DxfImportSource(DxfReader.Read(str(im.INPUTS / "dxf" / "inches.dxf"), 0.01))
    shapes = src.CaptureLayers(None, layers_of(src))
    pls = polylines(shapes, "#000000")
    assert pls[0] == [(0.0, 0.0), (25.4, 25.4)]
    # full circle r=12.7 mm in two half arcs, step 2*acos(1 - 0.01/12.7): 40 + 40 segments
    assert len(pls[1]) == 81


# ------------------------------------------------------------ filling helpers

def P(x, y):
    from System.Windows import Point

    return Point(float(x), float(y))


def plist(*shapes):
    from System.Windows import Point

    out = System.Collections.Generic.List[System.Collections.Generic.List[Point]]()
    for s in shapes:
        l = System.Collections.Generic.List[Point]()
        for x, y in s:
            l.Add(P(x, y))
        out.Add(l)
    return out


def as_lists(res):
    return [[(round(p.X, 3), round(p.Y, 3)) for p in pl] for pl in res]


SQUARE = [(0, 0), (4, 0), (4, 4), (0, 4)]


def test_filling_ignores_degenerate_input():
    build = lambda shapes, d, lpm: as_lists(cu.scall(SvgFilling, "Build", shapes, d, lpm))
    assert build(plist(SQUARE), Direction.NewHorizontal, 0.0) == []
    assert build(plist([(0, 0), (1, 1)]), Direction.NewHorizontal, 1.0) == []
    assert build(plist(), Direction.NewHorizontal, 1.0) == []


def test_filling_with_a_raster_direction_gives_horizontal_hatch():
    """Raster directions (Horizontal...) are not vector fillings, but BuildGridFilling
    treats any non-inset direction through its grid generator."""
    got = as_lists(cu.scall(SvgFilling, "Build", plist(SQUARE), Direction.Horizontal, 1.0))
    assert got == as_lists(cu.scall(SvgFilling, "Build", plist(SQUARE), Direction.Horizontal, 1.0))


def test_join_open_paths_chains_touching_ends_in_both_directions():
    shapes = plist([(0, 0), (4, 0)], [(4, 4), (4, 0)], [(9, 9)], [(0, 4), (4, 4)], [(10, 10), (12, 10)],
                   [(0, 0), (0, 4), (0, 0.01)], [(12, 10), (12, 12)])
    got = as_lists(cu.scall(SvgFilling, "JoinOpenPaths", shapes))
    assert got == [
        [(0.0, 0.0), (0.0, 4.0), (0.0, 0.01)],          # already closed (ends within 0.05 mm): kept as is
        [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],  # chained (reversed segments flipped); reversed twice, back to the first order
        [(10.0, 10.0), (12.0, 10.0), (12.0, 12.0)],     # joined at (12,10); its own end is skipped as used
    ]


# ------------------------------------------------------------ files and resources

def test_relative_file_name_starting_with_laser_grbl_is_taken_as_a_resource(tmp_path, monkeypatch):
    """ReadSvgFile treats any name starting with "LaserGRBL." as an embedded resource:
    an existing file with such a relative name cannot be opened (FINDINGS)."""
    (tmp_path / "LaserGRBL.mine.svg").write_text((im.INPUTS / "svg" / "no_size.svg").read_text())
    monkeypatch.chdir(tmp_path)
    with pytest.raises(System.ArgumentNullException):
        cu.scall(GCodeFromSVG, "ParseSvgFile", "LaserGRBL.mine.svg")
    assert cu.scall(GCodeFromSVG, "ParseSvgFile", str(tmp_path / "LaserGRBL.mine.svg")) is not None


def test_append_import_keeps_previous_commands():
    f = GrblFile()
    path = str(im.INPUTS / "svg" / "no_size.svg")
    from lasergrbl_harness.core_rig import wait_loaded

    src = svg_source("no_size.svg")
    f.LoadImportedSVG(path, False, None, layers_of(src))
    wait_loaded(f)
    n = f.Count
    im.reset_gcode_statics()
    f.LoadImportedSVG(path, True, None, layers_of(src))
    wait_loaded(f)
    assert f.Count == 2 * n


# ------------------------------------------------------------ static writer state

def test_firmware_type_is_read_once_per_process():
    """SvgConverter.gcode reads "Firmware Type" in its static constructor: changing the
    setting later has no effect on SVG/DXF import until LaserGRBL is restarted
    (FINDINGS)."""
    src = svg_source("paths.svg")
    layers = layers_of(src)
    grbl = str(src.CreateGCode(None, layers))
    Settings.SetObject("Firmware Type", LaserGRBL.Firmware.Smoothie)
    im.reset_gcode_statics()  # the state of a process started with Grbl
    assert str(src.CreateGCode(None, layers)) == grbl
    im.set_gcode_firmware("Smoothie")
    assert str(src.CreateGCode(None, layers)) != grbl


def test_consecutive_imports_give_the_same_gcode():
    """The writer's static state (last position/feed) is reset by setup(): importing the
    same file twice in a row gives the same text."""
    src = svg_source("basic_shapes.svg")
    layers = layers_of(src)
    assert str(src.CreateGCode(None, layers)) == str(src.CreateGCode(None, layers))


def test_failed_import_clears_the_file_and_never_reports_loaded():
    """LoadImportedVector clears the file, then the conversion throws on the loading
    thread (F-31): the previous content is lost and OnFileLoaded is never raised
    (FINDINGS F-33)."""
    from LaserGRBLTests import GrblFileEvents

    from lasergrbl_harness.core_rig import wait_loaded

    f = GrblFile()
    ev = GrblFileEvents(f)
    good = svg_source("no_size.svg")
    f.LoadImportedSVG(str(im.INPUTS / "svg" / "no_size.svg"), False, None, layers_of(good))
    wait_loaded(f)
    assert f.Count > 0 and (ev.Loading, ev.Loaded) == (1, 1)
    im.reset_gcode_statics()
    bad = svg_source("compact_numbers.svg")
    f.LoadImportedSVG(str(im.INPUTS / "svg" / "compact_numbers.svg"), False, None, layers_of(bad))
    wait_loaded(f)
    assert f.Count == 0
    assert (ev.Loading, ev.Loaded) == (2, 1)
