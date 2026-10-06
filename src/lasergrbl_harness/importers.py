"""Importer golden cases: input (file, pixels or parameters) + options -> G-code.

A case is a JSON file in ``fixtures/importers/cases/``; ``run_case(case)`` returns a
JSON-able dict that a future Rust implementation must reproduce through its own
adapter. Case kinds and their fields:

* ``generator``: ``generator`` ("cutting" | "greyscale" | "shake") and ``args``
  (the parameters of ``GrblFile.GenerateCuttingTest/GenerateGreyscaleTest/
  GenerateShakeTest``, by name, see ``GENERATOR_ARGS``).
* ``hershey``: ``text``, ``x``, ``y``, ``speed``, ``power``, ``horizontal``, ``ton``
  (``Hershey.CreateString``: commands only, no file analysis).
* ``svg`` / ``dxf``: ``input`` (path relative to ``fixtures/importers/inputs``) or,
  for svg, ``resource`` (the name of an svg embedded in LaserGRBL.exe),
  ``layers`` (list of ``{color, mode, speed, power, passes, fill, lines_per_mm}``,
  or omitted: every scanned color as a "Line" layer with ``layer_defaults``), and
  for dxf an optional ``spline_tolerance`` (mm, default: the setting / 0.01).
* ``svg_text``: ``input`` (an svg as written by autotrace), ``max_size`` (mm) and
  optional ``offset`` [x, y]: the conversion half of ``GrblFile.LoadImageCenterline``
  (``GCodeFromSVG.convertFromText`` with the same options; the autotrace step needs
  the Windows ``autotrace.exe`` and is not run). Output: ``converter_output``, the
  converter text split in lines.
* ``raster``: ``image`` (see ``parse_pixels``) and ``conf`` (the fields of
  ``GrblFile.L2LConf`` by name; ``dir`` is an ``ImageProcessor.Direction`` name),
  loaded with ``GrblFile.LoadImageL2L``.
* ``image_op``: ``image``, ``op`` and ``args``; output is the resulting pixels
  (``ImageTransform`` and dithering, see ``IMAGE_OPS``).

Every kind may carry ``settings``: LaserGRBL settings (key -> value) applied on top
of the defaults before running. Cases whose result depends on the GDI+
implementation (pixel operations drawn through ``Graphics``) carry
``platform_dependent`` with the reason: they were recorded with Mono's
libgdiplus and may differ on Windows GDI+ or in another implementation. Output fields:

* ``gcode``: the command text of every row of the resulting ``GrblFile``
* ``summary``: ``count``, ``estimated_time_s``, ``drawing_range`` and
  ``moving_range`` ([xmin, ymin, xmax, ymax] or null), with the machine
  configuration of ``golden.CONFIG``
* ``scan`` (svg/dxf): the color layers found in the file, ``[{color, count}]``
* ``error`` (svg/dxf, only when the conversion throws): exception type and message;
  ``GrblFile`` swallows it on its loading thread, ``gcode`` shows what is left
* ``pixels`` (image_op): rows of ``AARRGGBB`` hex tokens

Pixel images (``image``): ``{"pixels": ["RRGGBB RRGGBB ...", ...]}``, one string per
row, tokens of 2 (gray), 6 (RGB) or 8 (ARGB) hex digits.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "fixtures" / "importers" / "cases"
INPUTS = ROOT / "fixtures" / "importers" / "inputs"

GENERATOR_ARGS = {
    "cutting": ["f_col", "f_start", "f_end", "p_start", "p_end", "s_fixed", "f_text", "s_text", "title", "ton"],
    "greyscale": ["f_row", "s_col", "f_start", "f_end", "s_start", "s_end", "x_size", "y_size", "resolution",
                  "f_grid", "s_grid", "title", "f_text", "s_text", "ton"],
    "shake": ["axis", "flimit", "axislen", "cpower", "cspeed"],
}
GENERATOR_METHOD = {"cutting": "GenerateCuttingTest", "greyscale": "GenerateGreyscaleTest", "shake": "GenerateShakeTest"}

LAYER_DEFAULTS = {"mode": "Line", "speed": 1000, "power": 1000, "passes": 1}

L2L_DEFAULTS = {"res": 10.0, "fres": 10.0, "oX": 0.0, "oY": 0.0, "markSpeed": 1000, "borderSpeed": 1000,
                "minPower": 0, "maxPower": 1000, "lOn": "M3", "lOff": "M5", "dir": "Horizontal", "pwm": True,
                "vectorfilling": False, "firmwareType": "Grbl"}

IMAGE_OPS = ("grayscale", "threshold", "invert", "dither", "whitenize", "resize", "fill", "outline")


def load_cases() -> list[tuple[str, dict]]:
    return [(p.stem, json.loads(p.read_text())) for p in sorted(CASES.glob("*.json"))]


# ------------------------------------------------------------------ pixels

def parse_pixels(image: dict) -> list[list[tuple[int, int, int, int]]]:
    rows = []
    for line in image["pixels"]:
        row = []
        for tok in line.split():
            if len(tok) == 2:
                g = int(tok, 16)
                row.append((255, g, g, g))
            elif len(tok) == 6:
                row.append((255, int(tok[0:2], 16), int(tok[2:4], 16), int(tok[4:6], 16)))
            elif len(tok) == 8:
                row.append(tuple(int(tok[i:i + 2], 16) for i in (0, 2, 4, 6)))
            else:
                raise ValueError(f"bad pixel token {tok!r}")
        rows.append(row)
    if len({len(r) for r in rows}) != 1:
        raise ValueError("rows of different length")
    return rows


def make_bitmap(image: dict):
    from System.Drawing import Bitmap, Color

    rows = parse_pixels(image)
    bmp = Bitmap(len(rows[0]), len(rows))
    # a new Bitmap has the screen resolution on Windows (96 dpi) but 0 dpi on
    # libgdiplus, where ImageTransform.ResizeImage's SetResolution(0, 0) throws
    bmp.SetResolution(96, 96)
    for y, row in enumerate(rows):
        for x, (a, r, g, b) in enumerate(row):
            bmp.SetPixel(x, y, Color.FromArgb(a, r, g, b))
    return bmp


def dump_bitmap(bmp) -> list[str]:
    out = []
    for y in range(bmp.Height):
        toks = []
        for x in range(bmp.Width):
            c = bmp.GetPixel(x, y)
            toks.append(f"{c.A:02X}{c.R:02X}{c.G:02X}{c.B:02X}")
        out.append(" ".join(toks))
    return out


# ------------------------------------------------------------------ C# host

_GCODE_PRISTINE: dict | None = None


def _gcode_type():
    from LaserGRBL import GrblFile

    from . import clr_util as cu

    return cu.clr_type(GrblFile).Assembly.GetType("LaserGRBL.SvgConverter.gcode")


def reset_gcode_statics() -> None:
    """``SvgConverter.gcode`` is a static class whose state survives between imports
    (and whose firmware type is read once, by its static constructor). Every case
    starts from the state of a fresh process: a snapshot taken the first time,
    with the default settings."""
    global _GCODE_PRISTINE
    from System.Reflection import BindingFlags

    t = _gcode_type()
    fields = [f for f in t.GetFields(BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public)
              if not f.IsLiteral and not f.IsInitOnly]
    if _GCODE_PRISTINE is None:
        _GCODE_PRISTINE = {str(f.Name): f.GetValue(None) for f in fields}
    from System.Text import StringBuilder

    from . import clr_util as cu

    for f in fields:
        v = _GCODE_PRISTINE[str(f.Name)]
        if str(f.FieldType.Name) == "StringBuilder":
            v = StringBuilder()
        f.SetValue(None, cu._coerce(v, f.FieldType))


def set_gcode_firmware(name: str) -> None:
    """What the static constructor of ``gcode`` would have read at startup."""
    import LaserGRBL
    from System.Reflection import BindingFlags

    f = _gcode_type().GetField("firmwareType", BindingFlags.Static | BindingFlags.NonPublic)
    f.SetValue(None, getattr(LaserGRBL.Firmware, name))


def configure_machine() -> None:
    import System
    from LaserGRBL import GrblConfST, GrblCore

    from .golden import CONFIG

    d = System.Collections.Generic.Dictionary[int, str]()
    for k, v in CONFIG.items():
        d[k] = v
    GrblCore.Configuration = GrblConfST(GrblCore.GrblVersionInfo(1, 1, "f"), d)


def apply_settings(settings: dict) -> None:
    import System
    import LaserGRBL
    from LaserGRBL import Settings

    for k, v in settings.items():
        if k == "Firmware Type":
            v = getattr(LaserGRBL.Firmware, v)
        elif isinstance(v, bool) or isinstance(v, str):
            pass
        elif isinstance(v, int):
            v = System.Int32(v)
        elif isinstance(v, float):
            v = System.Double(v)
        Settings.SetObject(k, v)


def _num(d) -> float:
    return round(float(str(d)), 6)


def _xy(r):
    if not r.ValidRange:
        return None
    return [_num(r.X.Min), _num(r.Y.Min), _num(r.X.Max), _num(r.Y.Max)]


def file_result(f) -> dict:
    return {
        "gcode": [str(c.Command) for c in f],
        "summary": {
            "count": int(f.Count),
            "estimated_time_s": round(f.EstimatedTime.TotalSeconds, 3),
            "drawing_range": _xy(f.Range.DrawingRange),
            "moving_range": _xy(f.Range.MovingRange),
        },
    }


def make_layers(case: dict, scanned):
    import System
    from LaserGRBL.RasterConverter import ImageProcessor
    from LaserGRBL.SvgConverter import SvgColorLayer, SvgLayerMode

    specs = case.get("layers")
    if specs is None:
        d = {**LAYER_DEFAULTS, **case.get("layer_defaults", {})}
        specs = [{"color": str(l.Color), **d} for l in scanned]
    layers = System.Collections.Generic.List[SvgColorLayer]()
    for s in specs:
        s = {**LAYER_DEFAULTS, **s}
        l = SvgColorLayer(s["color"])
        l.Mode = getattr(SvgLayerMode, s["mode"])
        l.Speed = int(s["speed"])
        l.Power = int(s["power"])
        l.Passes = int(s["passes"])
        if "fill" in s:
            l.FillDirection = getattr(ImageProcessor.Direction, s["fill"])
        if "lines_per_mm" in s:
            l.LinesPerMM = float(s["lines_per_mm"])
        layers.Add(l)
    return layers


def _scan(scanned) -> list[dict]:
    return [{"color": str(l.Color), "count": int(l.ElementCount)} for l in scanned]


def run_csharp(case: dict) -> dict:
    import LaserGRBL
    from LaserGRBL import GrblFile

    from . import clr_util as cu
    from .core_rig import wait_loaded

    configure_machine()
    reset_gcode_statics()
    apply_settings(case.get("settings", {}))
    set_gcode_firmware(case.get("settings", {}).get("Firmware Type", "Grbl"))
    kind = case["kind"]

    if kind == "hershey":
        from LaserGRBL.Hershey import Hershey

        cmds = Hershey.CreateString(case["text"], float(case["x"]), float(case["y"]), int(case["speed"]),
                                    int(case["power"]), bool(case["horizontal"]), case["ton"])
        return {"gcode": [str(c.Command) for c in cmds]}

    f = GrblFile()
    if kind == "generator":
        gen = case["generator"]
        args = [case["args"][n] for n in GENERATOR_ARGS[gen]]
        cu.call(f, GENERATOR_METHOD[gen], *args)
        return file_result(f)

    if kind in ("svg", "dxf"):
        # "resource": an svg embedded in LaserGRBL.exe, opened by its resource name
        path = case["resource"] if "resource" in case else str(INPUTS / case["input"])
        if kind == "svg":
            from LaserGRBL.SvgConverter import SvgImportSource

            # GCodeFromSVG is an internal class: reached by reflection
            xml = cu.scall(cu.clr_type(GrblFile).Assembly.GetType("LaserGRBL.SvgConverter.GCodeFromSVG"), "ParseSvgFile", path)
            source = SvgImportSource(xml)
        else:
            from LaserGRBL.SvgConverter import DxfImportSource, DxfReader

            tol = case.get("spline_tolerance")
            drawing = DxfReader.Read(path) if tol is None else DxfReader.Read(path, float(tol))
            source = DxfImportSource(drawing)
        scanned = source.ScanLayers()
        layers = make_layers(case, scanned)
        # GrblFile loads on a background thread and only logs exceptions: run the
        # conversion once here to report the error (the load below then shows what
        # the file contains after the failure)
        error = None
        try:
            source.CreateGCode(None, layers)
        except Exception as e:  # noqa: BLE001  (any CLR exception is the result)
            error = f"{e.GetType().FullName}: {e.Message}" if hasattr(e, "GetType") else repr(e)
        reset_gcode_statics()
        set_gcode_firmware(case.get("settings", {}).get("Firmware Type", "Grbl"))
        if kind == "svg" and not case.get("via_source"):
            f.LoadImportedSVG(path, False, None, layers)
        else:
            f.LoadImportedVector(path, source, False, None, layers)
        wait_loaded(f)
        out = {"scan": _scan(scanned), **file_result(f)}
        if error is not None:
            out["error"] = error
        return out

    if kind == "svg_text":
        import System
        from System.Drawing import PointF
        from LaserGRBL.SvgConverter import ColorFilter

        conv = System.Activator.CreateInstance(cu.clr_type(GrblFile).Assembly.GetType("LaserGRBL.SvgConverter.GCodeFromSVG"))
        # same option setup as GrblFile.LoadImageCenterline
        st = case.get("settings", {})
        cu.set(conv, "GCodeXYFeed", float(st.get("GrayScaleConversion.VectorizeOptions.BorderSpeed", 1000)))
        cu.set(conv, "SvgScaleApply", True)
        cu.set(conv, "SvgMaxSize", float(case["max_size"]))
        ox, oy = case.get("offset", [0, 0])
        cu.set(conv, "UserOffset", PointF(float(ox), float(oy)))
        cu.set(conv, "UseLegacyBezier", not bool(st.get("Vector.UseSmartBezier", True)))
        text = (INPUTS / case["input"]).read_text()
        out = str(cu.call(conv, "convertFromText", text, None, False, ColorFilter.All))
        return {"converter_output": out.replace("\r\n", "\n").split("\n")}

    if kind == "raster":
        conf = GrblFile.L2LConf()
        for k, v in {**L2L_DEFAULTS, **case.get("conf", {})}.items():
            if k == "dir":
                v = getattr(LaserGRBL.RasterConverter.ImageProcessor.Direction, v)
            elif k == "firmwareType":
                v = getattr(LaserGRBL.Firmware, v)
            setattr(conf, k, v)
        f.LoadImageL2L(make_bitmap(case["image"]), "image", conf, False, None)
        return file_result(f)

    if kind == "image_op":
        return {"pixels": dump_bitmap(image_op(case["op"], make_bitmap(case["image"]), case.get("args", {})))}

    raise ValueError(f"unknown case kind {kind!r}")


def image_op(op: str, bmp, args: dict):
    from System.Drawing import Color, Point, Size
    from System.Drawing.Drawing2D import InterpolationMode
    from LaserGRBL.RasterConverter import ImageTransform

    from . import clr_util as cu

    if op == "grayscale":
        return ImageTransform.GrayScale(bmp, float(args.get("r", 1)), float(args.get("g", 1)), float(args.get("b", 1)),
                                        float(args.get("brightness", 0)), float(args.get("contrast", 1)),
                                        getattr(ImageTransform.Formula, args.get("formula", "SimpleAverage")))
    if op == "threshold":
        return ImageTransform.Threshold(bmp, float(args["threshold"]), bool(args.get("apply", True)))
    if op == "invert":
        return ImageTransform.InvertingImage(bmp)
    if op == "dither":
        return ImageTransform.DitherImage(bmp, getattr(ImageTransform.DitheringMode, args["mode"]))
    if op == "whitenize":
        return ImageTransform.Whitenize(bmp, int(args["threshold"]), bool(args.get("demo", False)))
    if op == "resize":
        return ImageTransform.ResizeImage(bmp, Size(int(args["width"]), int(args["height"])), bool(args.get("killalfa", True)),
                                          getattr(InterpolationMode, args.get("interpolation", "NearestNeighbor")))
    if op == "fill":
        a, r, g, b = parse_pixels({"pixels": [args["color"]]})[0][0]
        return cu.scall(ImageTransform, "Fill", bmp, Point(*args["at"]), Color.FromArgb(a, r, g, b), int(args["tolerance"]))
    if op == "outline":
        return cu.scall(ImageTransform, "Outliner", bmp, Point(*args["at"]))
    raise ValueError(f"unknown image op {op!r}")


def run_case(case: dict) -> dict:
    kind = os.environ.get("LASERGRBL_HOST", "csharp")
    if kind == "csharp":
        return run_csharp(case)
    raise RuntimeError(f"no importer adapter for LASERGRBL_HOST={kind!r}")
