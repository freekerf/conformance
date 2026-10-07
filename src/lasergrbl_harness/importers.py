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
* ``centerline``: ``image``, ``autotrace_output`` (an svg under ``inputs/`` that the
  autotrace double prints, see ``fake_autotrace``) and optional ``thresholds``
  (``use_corner``, ``corner``, ``use_line``, ``line``; default the dialog's: on, 110 /
  on, 10), loaded with ``GrblFile.LoadImageCenterline``. Speed, power, laser
  commands and offset come from the settings the dialog stores (``settings``), not
  from ``conf``. Extra output:
  ``autotrace_args`` (the command line LaserGRBL builds, temp png as ``<png>``) and
  ``autotrace_input`` (the pixels of the png it hands to autotrace).
* ``raster``: ``image`` (see ``parse_pixels``) and ``conf`` (the fields of
  ``GrblFile.L2LConf`` by name; ``dir`` is an ``ImageProcessor.Direction`` name),
  loaded with ``GrblFile.LoadImageL2L``.
* ``potrace``: ``image``, ``conf`` (as ``raster``) and ``potrace`` (``spot_removal``,
  ``smoothing``, ``optimize`` - each null/omitted for "off" - and
  ``optimize_fast``), loaded with ``GrblFile.LoadImagePotrace`` (vectorize: borders
  traced by CsPotrace, optional vector filling (``New*`` directions, PotraceClipper)
  or raster filling (``Horizontal``/``Vertical``/``Diagonal``, drawn through GDI+).
* ``image_processor``: the raster dialog pipeline (``RasterConverter.ImageProcessor``):
  ``image`` (saved as a PNG and opened by the real constructor), optional ``box``
  [w, h] (preview frame, default [100, 100]), ``edits`` (list of ``{"op": ...}``
  applied first: ``crop`` (``rect`` [x, y, w, h], ``rsize`` [w, h]), ``autotrim``,
  ``rotate_cw``, ``rotate_ccw``, ``invert``, ``flip_h`` (upside down), ``flip_v``
  (mirror), ``revert`` (back to the file image), ``fill`` (``at``, ``rsize``, ``color``,
  ``tolerance``), ``outline`` (``at``, ``rsize``)), ``options`` (ImageProcessor
  properties by name on top of ``IP_DEFAULTS``, the dialog defaults; enums by name)
  and ``target`` (fields on top of ``IP_TARGET_DEFAULTS``: ``size`` [w, h] mm,
  ``offset``, speeds, powers, laser on/off). Like the dialog (``StoreSettings``) the
  runner stores the target values in the settings before generating (Centerline
  reads them from there). G-code generation (``DoTrueWork``) runs on the test thread. Output: ``gcode``/``summary`` and ``generation_error``
  (``GenerationComplete`` argument, null on success); with ``autotrace_output`` the
  autotrace double is installed (Centerline tool). Every result goes through
  GDI+ (resize, grayscale), so these cases are ``platform_dependent``.
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
row, tokens of 2 (gray), 6 (RGB) or 8 (ARGB) hex digits; or ``{"ascii": ["..##..",
...]}``, one character per pixel, ``#`` black and ``.`` white.

FreeKerf (``LASERGRBL_HOST=rust``) runs a case with ``freekerf import-case`` (the case
on stdin, ``--inputs`` this directory), which prints the same JSON. The svg embedded in
LaserGRBL.exe that ``resource`` cases open is a file of ``inputs/resources/`` named by
its resource name. A case may carry ``"rust_divergence": "DIV-NNN"`` when FreeKerf
intentionally differs (strict xfail for the Rust host only, see ``tests/conftest.py``).
"""

from __future__ import annotations

import contextlib
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


# RasterToLaserForm.LoadSettings / ConvertSizeAndOptionForm defaults
IP_DEFAULTS = {"SelectedTool": "Line2Line", "LineDirection": "Horizontal", "Quality": 3.0, "LinePreview": False,
               "UseSpotRemoval": False, "SpotRemoval": 2.0, "UseSmoothing": False, "Smoothing": 1.0,
               "UseOptimize": False, "UseAdaptiveQuality": False, "Optimize": 0.2, "UseDownSampling": False,
               "DownSampling": 2.0, "OptimizeFast": False, "FillingDirection": "None", "FillingQuality": 3.0,
               "Interpolation": "HighQualityBicubic", "Formula": "SimpleAverage", "Red": 100, "Green": 100,
               "Blue": 100, "Brightness": 100, "Contrast": 100, "UseThreshold": False, "Threshold": 50,
               "WhiteClip": 5, "DitheringMode": "FloydSteinberg", "UseLineThreshold": True, "LineThreshold": 10,
               "UseCornerThreshold": True, "CornerThreshold": 110}
IP_TARGET_DEFAULTS = {"size": [1.0, 1.0], "offset": [0.0, 0.0], "border_speed": 1000, "mark_speed": 1000,
                      "min_power": 0, "max_power": 1000, "laser_on": "M3", "laser_off": "M5"}


CENTERLINE_DEFAULTS = {"use_corner": True, "corner": 110, "use_line": True, "line": 10}

_FAKE_AUTOTRACE = """#!/bin/sh
# autotrace test double: records its command line and the png it was given,
# then prints a canned svg
for a in "$@"; do printf '%s\\n' "$a"; last="$a"; done > "$LG_AUTOTRACE_LOG"
cp "$last" "$LG_AUTOTRACE_LOG.png" 2>/dev/null
cat "$LG_AUTOTRACE_SVG"
"""


def _set_main_args(argv: list[str]) -> None:
    """Environment.GetCommandLineArgs() of the embedded Mono runtime (empty under
    pythonnet, where Application.ExecutablePath therefore throws)."""
    import ctypes

    lib = ctypes.CDLL(None)
    lib.mono_runtime_set_main_args.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
    buf = (ctypes.c_char_p * (len(argv) + 1))(*[a.encode() for a in argv], None)
    _set_main_args.keep = buf  # Mono copies the strings, keep the buffer anyway
    lib.mono_runtime_set_main_args(len(argv), buf)


@contextlib.contextmanager
def fake_autotrace(svg: Path, workdir: Path):
    """Installs the autotrace double for the duration of the block.

    LaserGRBL runs ``Path.Combine(GrblCore.ExePath, "Autotrace\\autotrace.exe")``.
    ``ExePath`` comes from ``Application.ExecutablePath`` = argv[0]: argv[0] is set to
    a LaserGRBL.exe in ``workdir`` (it need not exist). Mono's process creation turns
    the backslash into ``/``, so the double is ``<workdir>/bin/Autotrace/autotrace.exe``:
    a shell script that records its arguments and the png and prints ``svg``. Yields
    the path of the argument log (the png copy is ``<log>.png``)."""
    bindir = workdir / "bin"
    (bindir / "Autotrace").mkdir(parents=True, exist_ok=True)
    exe = bindir / "Autotrace" / "autotrace.exe"
    exe.write_text(_FAKE_AUTOTRACE)
    exe.chmod(0o755)
    log = workdir / "autotrace.log"
    os.environ["LG_AUTOTRACE_SVG"] = str(svg)
    os.environ["LG_AUTOTRACE_LOG"] = str(log)
    _set_main_args([str(bindir / "LaserGRBL.exe")])
    try:
        yield log
    finally:
        _set_main_args([])
        os.environ.pop("LG_AUTOTRACE_SVG", None)
        os.environ.pop("LG_AUTOTRACE_LOG", None)


def autotrace_record(log: Path) -> dict:
    from System.Drawing import Bitmap

    if not log.exists():
        return {"autotrace_args": None, "autotrace_input": None}
    args = log.read_text().splitlines()
    png = Path(str(log) + ".png")
    pixels = None
    if png.exists():
        bmp = Bitmap(str(png))
        pixels = dump_bitmap(bmp)
        bmp.Dispose()
    return {"autotrace_args": args[:-1] + ["<png>"] if args else args, "autotrace_input": pixels}


def load_cases() -> list[tuple[str, dict]]:
    return [(p.stem, json.loads(p.read_text())) for p in sorted(CASES.glob("*.json"))]


# ------------------------------------------------------------------ pixels

def parse_pixels(image: dict) -> list[list[tuple[int, int, int, int]]]:
    if "ascii" in image:
        image = {"pixels": [" ".join({"#": "00", ".": "FF"}[c] for c in line) for line in image["ascii"]]}
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
    bmp = Bitmap(len(rows[0]), len(rows))  # 96 dpi, as on Windows (native/lgshim.c)
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


# settings LaserGRBL reads as float (Settings.GetObject only returns a value stored
# with exactly the requested type, anything else silently gives the default)
SINGLE_SETTINGS = {"GrayScaleConversion.Gcode.Offset.X", "GrayScaleConversion.Gcode.Offset.Y"}


def apply_settings(settings: dict) -> None:
    import System
    import LaserGRBL
    from LaserGRBL import Settings

    for k, v in settings.items():
        if k == "Firmware Type":
            v = getattr(LaserGRBL.Firmware, v)
        elif isinstance(v, bool) or isinstance(v, str):
            pass
        elif k in SINGLE_SETTINGS:
            v = System.Single(v)
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

    if kind == "centerline":
        import tempfile

        conf = GrblFile.L2LConf()
        for k, v in {**L2L_DEFAULTS, **case.get("conf", {})}.items():
            if k == "dir":
                v = getattr(LaserGRBL.RasterConverter.ImageProcessor.Direction, v)
            elif k == "firmwareType":
                v = getattr(LaserGRBL.Firmware, v)
            setattr(conf, k, v)
        th = {**CENTERLINE_DEFAULTS, **case.get("thresholds", {})}
        with tempfile.TemporaryDirectory(prefix="lg-ct-") as tmp:
            with fake_autotrace(INPUTS / case["autotrace_output"], Path(tmp)) as log:
                cu.call(f, "LoadImageCenterline", make_bitmap(case["image"]), "image", bool(th["use_corner"]),
                        int(th["corner"]), bool(th["use_line"]), int(th["line"]), conf, False, None)
                return {**file_result(f), **autotrace_record(log)}

    if kind in ("raster", "potrace"):
        conf = GrblFile.L2LConf()
        for k, v in {**L2L_DEFAULTS, **case.get("conf", {})}.items():
            if k == "dir":
                v = getattr(LaserGRBL.RasterConverter.ImageProcessor.Direction, v)
            elif k == "firmwareType":
                v = getattr(LaserGRBL.Firmware, v)
            setattr(conf, k, v)
        if kind == "raster":
            f.LoadImageL2L(make_bitmap(case["image"]), "image", conf, False, None)
        else:
            from System import Decimal

            po = case.get("potrace", {})
            spot, smooth, opt = po.get("spot_removal"), po.get("smoothing"), po.get("optimize")
            f.LoadImagePotrace(make_bitmap(case["image"]), "image", spot is not None, int(spot or 0),
                               smooth is not None, Decimal(float(smooth or 0)), opt is not None,
                               Decimal(float(opt or 0)), bool(po.get("optimize_fast", False)), conf, False, None)
        return file_result(f)

    if kind == "image_processor":
        import tempfile

        from .core_rig import CoreRig
        from LaserGRBLTests import ImageProcessorProbe

        rig = CoreRig(events=False)
        probe = ImageProcessorProbe()
        tmp = tempfile.mkdtemp(prefix="lg-ip-")
        try:
            ip = make_image_processor(rig.core, case, Path(tmp) / "image.png")
            store_dialog_settings(ip)
            cu.set(ip, "mSuspended", False)
            extra = {}
            if "autotrace_output" in case:
                with fake_autotrace(INPUTS / case["autotrace_output"], Path(tmp)) as log:
                    cu.call(ip, "DoTrueWork")
                    extra = autotrace_record(log)
            else:
                cu.call(ip, "DoTrueWork")
            res = {**file_result(rig.core.LoadedFile), **extra}
            err = probe.LastError
            res["generation_error"] = None if err is None else f"{err.GetType().FullName}: {err.Message}"
            ip.Dispose()
            return res
        finally:
            probe.Detach()
            rig.close()
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)

    if kind == "image_op":
        return {"pixels": dump_bitmap(image_op(case["op"], make_bitmap(case["image"]), case.get("args", {})))}

    raise ValueError(f"unknown case kind {kind!r}")


def make_image_processor(core, case: dict, png: Path):
    """An ImageProcessor on ``case["image"]`` saved as ``png``, suspended (no preview
    thread), with the case edits applied and options/target set."""
    import System
    from System.Drawing import Color, Point, PointF, Rectangle, Size, SizeF
    from LaserGRBL.RasterConverter import ImageProcessor

    from . import clr_util as cu

    make_bitmap(case["image"]).Save(str(png))
    ip = ImageProcessor(core, str(png), Size(*case.get("box", [100, 100])), bool(case.get("append", False)))
    t = cu.clr_type(ImageProcessor)
    for name, value in {**IP_DEFAULTS, **case.get("options", {})}.items():
        ptype = t.GetProperty(name).PropertyType
        if ptype.IsEnum:
            value = System.Enum.Parse(ptype, value)
        elif ptype == cu.clr_type(System.Decimal):
            value = System.Decimal(float(value))
        setattr(ip, name, value)
    for e in case.get("edits", []):
        op = e["op"]
        if op == "crop":
            ip.CropImage(Rectangle(*e["rect"]), Size(*e["rsize"]))
        elif op == "autotrim":
            ip.AutoTrim()
        elif op == "rotate_cw":
            ip.RotateCW()
        elif op == "rotate_ccw":
            ip.RotateCCW()
        elif op == "invert":
            ip.Invert()
        elif op == "flip_h":
            ip.FlipH()
        elif op == "flip_v":
            ip.FlipV()
        elif op == "revert":
            ip.Revert()
        elif op == "fill":
            a, r, g, b = parse_pixels({"pixels": [e["color"]]})[0][0]
            cu.call(ip, "Fill", Point(*e["at"]), Size(*e["rsize"]), Color.FromArgb(a, r, g, b), int(e["tolerance"]))
        elif op == "outline":
            cu.call(ip, "Outliner", Point(*e["at"]), Size(*e["rsize"]))
        else:
            raise ValueError(f"unknown edit {op!r}")
    tg = {**IP_TARGET_DEFAULTS, **case.get("target", {})}
    ip.TargetSize = SizeF(*(float(v) for v in tg["size"]))
    ip.TargetOffset = PointF(*(float(v) for v in tg["offset"]))
    ip.BorderSpeed, ip.MarkSpeed = int(tg["border_speed"]), int(tg["mark_speed"])
    ip.MinPower, ip.MaxPower = int(tg["min_power"]), int(tg["max_power"])
    ip.LaserOn, ip.LaserOff = tg["laser_on"], tg["laser_off"]
    return ip


def store_dialog_settings(ip) -> None:
    """The part of RasterToLaserForm.StoreSettings (run before GenerateGCode) that the
    generation reads back: the SVG writer used by Centerline takes these settings."""
    import System
    from LaserGRBL import Settings

    for key, value in (("GrayScaleConversion.VectorizeOptions.BorderSpeed", System.Int32(ip.BorderSpeed)),
                       ("GrayScaleConversion.Gcode.Speed.Mark", System.Int32(ip.MarkSpeed)),
                       ("GrayScaleConversion.Gcode.LaserOptions.LaserOn", ip.LaserOn),
                       ("GrayScaleConversion.Gcode.LaserOptions.LaserOff", ip.LaserOff),
                       ("GrayScaleConversion.Gcode.LaserOptions.PowerMin", System.Int32(ip.MinPower)),
                       ("GrayScaleConversion.Gcode.LaserOptions.PowerMax", System.Int32(ip.MaxPower)),
                       ("GrayScaleConversion.Gcode.Offset.X", System.Single(ip.TargetOffset.X)),
                       ("GrayScaleConversion.Gcode.Offset.Y", System.Single(ip.TargetOffset.Y))):
        Settings.SetObject(key, value)


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


_RUST_KINDS: list[str] | None = None


def rust_kinds() -> list[str]:
    """Case kinds the FreeKerf build runs (``freekerf import-case --kinds``); none for a
    build without that command (every importer case is then skipped)."""
    global _RUST_KINDS
    if _RUST_KINDS is None:
        import subprocess

        from .host import freekerf_bin

        out = subprocess.run([freekerf_bin(), "import-case", "--kinds"], capture_output=True, text=True)
        _RUST_KINDS = out.stdout.split() if out.returncode == 0 else []
    return _RUST_KINDS


def run_rust(case: dict) -> dict:
    """FreeKerf: ``freekerf import-case - --inputs fixtures/importers/inputs``."""
    import subprocess

    from .host import freekerf_bin

    out = subprocess.run([freekerf_bin(), "import-case", "-", "--inputs", str(INPUTS)], input=json.dumps(case),
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"freekerf import-case failed: {out.stderr.strip()}")
    return json.loads(out.stdout)


def run_case(case: dict) -> dict:
    kind = os.environ.get("LASERGRBL_HOST", "csharp")
    if kind == "csharp":
        return run_csharp(case)
    if kind == "rust":
        return run_rust(case)
    raise RuntimeError(f"no importer adapter for LASERGRBL_HOST={kind!r}")
