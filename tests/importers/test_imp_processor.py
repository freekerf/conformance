"""RasterConverter.ImageProcessor: the raster dialog pipeline (image edits, the
bitmap handed to GrblFile per tool, resolution choice, preview/generation threads).
The G-code of whole runs is golden (fixtures/importers/cases/ip_*.json)."""

import System
import pytest
from System.Drawing import Rectangle, Size
from System.Drawing.Drawing2D import InterpolationMode

from LaserGRBL.RasterConverter import ImageProcessor, ImageTransform

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness import importers as im
from lasergrbl_harness.core_rig import CoreRig
from LaserGRBLTests import ImageProcessorProbe

Tool = ImageProcessor.Tool
GRAD = {"pixels": [" ".join(f"{v:02X}" for v in range(0, 256, 32))] * 4}
COLOR = {"pixels": ["FF0000 00FF00 0000FF 808080", "FFFF00 00FFFF FF00FF 202020", "000000 FFFFFF 404040 C0C0C0"]}


@pytest.fixture
def make_ip(tmp_path):
    """Factory: ImageProcessor on a case-like dict (suspended, dialog defaults)."""
    rig = CoreRig(events=False)
    made = []

    def make(image=GRAD, **case):
        ip = im.make_image_processor(rig.core, {"image": image, **case}, tmp_path / f"img{len(made)}.png")
        made.append(ip)
        return ip

    make.rig = rig
    yield make
    for ip in made:
        try:
            ip.Dispose()
        except Exception:
            pass
    rig.close()


@pytest.fixture
def probe():
    p = ImageProcessorProbe()
    yield p
    p.Detach()


def produce(ip, w, h):
    return im.dump_bitmap(cu.call(ip, "ProduceBitmap", ip.TrueOriginal, Size(w, h)))


# ------------------------------------------------------------ bitmap per tool

def reference_line2line(ip, w, h, threshold=True):
    """The documented pipeline of ProduceBitmap2 composed from ImageTransform calls."""
    resized = ImageTransform.ResizeImage(ip.TrueOriginal, Size(w, h), False, ip.Interpolation)
    formula = ImageTransform.Formula.SimpleAverage if ip.IsGrayScale else ip.Formula
    gray = ImageTransform.GrayScale(resized, ip.Red / 100.0, ip.Green / 100.0, ip.Blue / 100.0,
                                    -((100 - ip.Brightness) / 100.0), ip.Contrast / 100.0, formula)
    white = ImageTransform.Whitenize(gray, ip.WhiteClip, False)
    return white if not threshold else ImageTransform.Threshold(white, ip.Threshold / 100.0, ip.UseThreshold)


@pytest.mark.parametrize("options", [
    {},
    {"Formula": "Custom", "Red": 150, "Green": 60, "Blue": 40, "Brightness": 120, "Contrast": 150, "WhiteClip": 20,
     "UseThreshold": True, "Threshold": 40},
    {"Interpolation": "NearestNeighbor", "Brightness": 70, "Contrast": 80, "Formula": "WeightAverage"},
])
def test_line2line_bitmap_is_resize_grayscale_whitenize_threshold(make_ip, options):
    ip = make_ip(COLOR, options=options)
    assert ip.IsGrayScale is False
    assert produce(ip, 8, 6) == im.dump_bitmap(reference_line2line(ip, 8, 6))


def test_vectorize_bitmap_is_the_same_as_line2line(make_ip):
    ip = make_ip(COLOR, options={"SelectedTool": "Vectorize", "UseThreshold": True, "Threshold": 30})
    assert produce(ip, 8, 6) == im.dump_bitmap(reference_line2line(ip, 8, 6))


def test_dithering_bitmap_dithers_after_whitenize(make_ip):
    ip = make_ip(COLOR, options={"SelectedTool": "Dithering", "DitheringMode": "Burks", "UseThreshold": True})
    expected = ImageTransform.DitherImage(reference_line2line(ip, 8, 6, threshold=False), ImageTransform.DitheringMode.Burks)
    assert produce(ip, 8, 6) == im.dump_bitmap(expected)


def test_centerline_bitmap_applies_the_user_threshold_then_50_percent(make_ip):
    ip = make_ip(COLOR, options={"SelectedTool": "Centerline", "UseThreshold": True, "Threshold": 30})
    first = reference_line2line(ip, 8, 6)
    assert produce(ip, 8, 6) == im.dump_bitmap(ImageTransform.Threshold(first, 0.5, True))


def test_no_processing_bitmap_is_the_original_in_gray(make_ip):
    """NoProcessing ignores the requested size and every parameter: GrayScale with
    zero weights at the original size."""
    ip = make_ip(COLOR, options={"SelectedTool": "NoProcessing", "Brightness": 10, "UseThreshold": True})
    expected = ImageTransform.GrayScale(ip.TrueOriginal, 0, 0, 0, 0, 1, ImageTransform.Formula.SimpleAverage)
    assert produce(ip, 50, 50) == im.dump_bitmap(expected)


def test_vectorize_downsampling_resizes_first(make_ip):
    ip = make_ip(COLOR, options={"SelectedTool": "Vectorize", "UseDownSampling": True, "DownSampling": 2})
    down = ImageTransform.ResizeImage(ip.TrueOriginal, Size(4, 3), False, InterpolationMode.HighQualityBicubic)
    ref = make_ip(COLOR)
    cu.set(ref, "mOriginal", down)
    assert produce(ip, 8, 6) == im.dump_bitmap(reference_line2line(ref, 8, 6))


@pytest.mark.parametrize("tool,ds", [("Vectorize", 1), ("Line2Line", 2)])
def test_downsampling_only_for_vectorize_and_factor_above_1(make_ip, tool, ds):
    ip = make_ip(COLOR, options={"SelectedTool": tool, "UseDownSampling": True, "DownSampling": ds})
    assert produce(ip, 8, 6) == im.dump_bitmap(reference_line2line(ip, 8, 6))


# ------------------------------------------------------------ gray detection

def test_gray_detection_samples_every_tenth_pixel():
    """TestGrayScale looks at pixels (0,0), (0,10), (10,0)... only, with a
    tolerance of 20 per channel pair: colors off that grid are not seen (FINDINGS)."""
    rows = [" ".join("808080" for _ in range(12)) for _ in range(12)]
    rows[5] = " ".join("FF0000" for _ in range(12))  # a red row between samples
    assert grayish(rows)
    rows[0] = "FF0000 " + rows[0][7:]
    assert not grayish(rows)
    assert grayish([" ".join(["8F8080"] * 3)])  # diff 15 < 20
    assert not grayish([" ".join(["948080"] * 3)])  # diff 20


def grayish(rows):
    from LaserGRBL.RasterConverter import ImageProcessor as IP

    probe_ip = System.Runtime.Serialization.FormatterServices.GetUninitializedObject(cu.clr_type(IP))
    return cu.call(probe_ip, "TestGrayScale", im.make_bitmap({"pixels": rows}))


# ------------------------------------------------------------ resolution

@pytest.mark.parametrize("size,adaptive,expected", [
    (100.0, False, 10.0),
    (1e-6, True, 255.0),  # clamped up
    (1.0, True, 255.0),
    (10000.0, True, 25.5),  # 255 * (sqrt(10000)) ** -0.5
    (1e16, True, 4.0),  # clamped down
])
def test_vector_quality(size, adaptive, expected):
    assert cu.scall(ImageProcessor, "GetVectorQuality", size, adaptive) == pytest.approx(expected)


def test_centerline_without_autotrace_reports_an_xml_error(make_ip, probe):
    """Centerline needs the Windows autotrace.exe. LoadImageCenterline logs the
    autotrace failure and parses the empty output as SVG: the XmlException reaches
    GenerationComplete (the dialog shows it). With autotrace present this succeeds."""
    ip = make_ip(GRAD, options={"SelectedTool": "Centerline"}, target={"size": [0.8, 0.4]})
    cu.set(ip, "mSuspended", False)
    cu.call(ip, "DoTrueWork")
    assert probe.Complete == 1
    assert str(probe.LastError.GetType().Name) == "XmlException"


def test_generation_error_is_reported_through_the_event(make_ip, probe):
    ip = make_ip(GRAD, options={"Quality": 1}, target={"size": [0.8, 0.4], "laser_on": None})
    cu.set(ip, "mSuspended", False)
    cu.set(ip, "mOriginal", None)
    cu.call(ip, "DoTrueWork")
    assert probe.Complete == 1 and probe.LastError is not None


# ------------------------------------------------------------ edits and geometry

def test_aspect_ratio_helpers(make_ip):
    ip = make_ip(GRAD)  # 8 x 4
    assert ip.WidthToHeight(10.0) == pytest.approx(5.0)
    assert ip.HeightToWidht(10.0) == pytest.approx(20.0)


def test_preview_bitmap_fits_the_box_and_follows_resizes(make_ip):
    ip = make_ip(GRAD, box=[100, 100])
    assert (ip.Original.Width, ip.Original.Height) == (100, 50)
    cu.call(ip, "FormResize", Size(30, 60))
    assert (ip.Original.Width, ip.Original.Height) == (30, 15)
    ip.Interpolation = InterpolationMode.NearestNeighbor
    assert ip.Interpolation == InterpolationMode.NearestNeighbor
    ip.Interpolation = InterpolationMode.NearestNeighbor  # same value: nothing happens


def test_file_dpi_and_true_original(make_ip):
    ip = make_ip(GRAD)
    assert ip.FileDPI == 96
    assert (ip.TrueOriginal.Width, ip.TrueOriginal.Height) == (8, 4)


@pytest.mark.parametrize("rect,rsize", [((0, 0, 0, 10), (100, 50)), ((0, 0, 5, 5), (100, 50))])
def test_crop_ignores_empty_rectangles(make_ip, rect, rsize):
    """An empty selection, or one smaller than a source pixel, is ignored."""
    ip = make_ip(GRAD)
    ip.CropImage(Rectangle(*rect), Size(*rsize))
    assert (ip.TrueOriginal.Width, ip.TrueOriginal.Height) == (8, 4)


def test_crop_scales_preview_coordinates_to_the_image(make_ip):
    ip = make_ip(GRAD)
    ip.CropImage(Rectangle(25, 0, 50, 25), Size(100, 50))
    assert im.dump_bitmap(ip.TrueOriginal) == [" ".join(f"FF{v:02X}{v:02X}{v:02X}" for v in (64, 96, 128, 160))] * 2


def test_autotrim_needs_similar_uniform_borders(make_ip):
    # borders of different colors: nothing to trim
    rows = ["000000 000000 000000", "FFFFFF 808080 FFFFFF", "FFFFFF FFFFFF FFFFFF"]
    ip = make_ip({"pixels": rows})
    ip.AutoTrim()
    assert ip.TrueOriginal.Width == 3 and ip.TrueOriginal.Height == 3


def test_autotrim_with_non_uniform_edges_only_uses_the_uniform_ones(make_ip):
    rows = ["000000 FFFFFF FFFFFF FFFFFF",  # top row not uniform: skipped
            "000000 FFFFFF 404040 FFFFFF",
            "000000 FFFFFF FFFFFF FFFFFF"]  # left column black, others white
    ip = make_ip({"pixels": rows})
    ip.AutoTrim()
    assert (ip.TrueOriginal.Width, ip.TrueOriginal.Height) == (4, 3)


def test_autotrim_of_a_uniform_image_does_nothing(make_ip):
    ip = make_ip({"pixels": ["FFFFFF FFFFFF", "FFFFFF FFFFFF"]})
    ip.AutoTrim()
    assert (ip.TrueOriginal.Width, ip.TrueOriginal.Height) == (2, 2)


def test_autotrim_trims_every_side(make_ip):
    rows = ["FFFFFF FFFFFF FFFFFF FFFFFF", "FFFFFF 000000 202020 FFFFFF",
            "FFFFFF 404040 000000 FFFFFF", "FFFFFF FFFFFF FFFFFF FFFFFF"]
    ip = make_ip({"pixels": rows})
    ip.AutoTrim()
    assert im.dump_bitmap(ip.TrueOriginal) == ["FF000000 FF202020", "FF404040 FF000000"]


def test_clone_shares_the_original_and_copies_the_preview(make_ip):
    ip = make_ip(GRAD)
    c = ip.Clone()
    assert cu.get(c, "mOriginal").Equals(cu.get(ip, "mOriginal"))
    assert not cu.get(c, "mResized").Equals(cu.get(ip, "mResized"))
    assert cu.get(c, "TH") is None and cu.get(c, "MustExit") is None


def test_properties_round_trip(make_ip):
    ip = make_ip(GRAD)
    values = {"LineThreshold": 7, "UseLineThreshold": True, "CornerThreshold": 33, "UseCornerThreshold": True,
              "Demo": True, "LinePreview": True, "UseAdaptiveQuality": True}
    for k, v in values.items():
        setattr(ip, k, v)
        setattr(ip, k, v)  # unchanged value: no refresh
        assert getattr(ip, k) == v
    for k in ("Quality", "SpotRemoval", "Optimize", "Smoothing", "DownSampling", "FillingQuality"):
        setattr(ip, k, System.Decimal(1.5))
        setattr(ip, k, System.Decimal(1.5))
        assert float(str(getattr(ip, k))) == 1.5
    # every dialog option set again to its current value is a no-op
    for k in im.IP_DEFAULTS:
        setattr(ip, k, getattr(ip, k))
    assert ip.DitheringMode == ImageTransform.DitheringMode.FloydSteinberg


def test_flips_and_revert(make_ip):
    """FlipH turns the image upside down (RotateNoneFlipY), FlipV mirrors it
    (RotateNoneFlipX): flips around the horizontal / vertical axis. Revert goes back
    to the image as loaded, dropping every edit."""
    rows = ["000000 FFFFFF", "808080 404040"]
    ip = make_ip({"pixels": rows})
    ip.FlipH()
    assert im.dump_bitmap(ip.TrueOriginal) == ["FF808080 FF404040", "FF000000 FFFFFFFF"]
    ip.FlipV()
    assert im.dump_bitmap(ip.TrueOriginal) == ["FF404040 FF808080", "FFFFFFFF FF000000"]
    ip.CropImage(Rectangle(0, 0, 50, 50), Size(100, 100))
    ip.Revert()
    assert im.dump_bitmap(ip.TrueOriginal) == ["FF000000 FFFFFFFF", "FF808080 FF404040"]


# ------------------------------------------------------------ threads

def test_generation_without_subscribers(make_ip):
    """GenerationComplete with no handler: success, size error and exception paths."""
    for options, original in (({"Quality": 10}, True), ({"Quality": 0}, True), ({"Quality": 10}, False)):
        ip = make_ip(GRAD, options=options, target={"size": [0.8, 0.4]})
        cu.set(ip, "mSuspended", False)
        if not original:
            cu.set(ip, "mOriginal", None)
        cu.call(ip, "DoTrueWork")


def test_preview_without_subscribers(make_ip):
    ip = make_ip(GRAD)
    ip.Resume()
    th = cu.get(cu.get(ip, "Current"), "TH")
    assert th.Join(10000)


def test_preview_failure_is_swallowed(make_ip, probe):
    """An exception while producing the preview (here: down sampling to a 0 x 0
    bitmap) is only written to the debug output; no PreviewReady."""
    ip = make_ip(GRAD, options={"SelectedTool": "Vectorize", "UseDownSampling": True, "DownSampling": 1000})
    ip.Resume()
    th = cu.get(cu.get(ip, "Current"), "TH")
    assert th.Join(10000)
    assert probe.Begin == 1 and probe.Ready == 0


def test_generate_without_a_previous_preview(make_ip, probe):
    ip = make_ip(GRAD, options={"Quality": 10}, target={"size": [0.8, 0.4]})
    cu.set(ip, "mSuspended", False)
    ip.GenerateGCode()
    assert probe.WaitComplete(10000) and probe.LastError is None


def test_suspended_processor_does_not_generate(make_ip, probe):
    ip = make_ip(GRAD)
    ip.GenerateGCode()
    assert probe.Complete == 0 and probe.Begin == 0


def test_resume_previews_and_generate_runs_on_a_thread(make_ip, probe):
    ip = make_ip(GRAD, options={"Quality": 10}, target={"size": [0.8, 0.4]})
    ip.Resume()
    assert probe.WaitReady(10000)
    assert probe.Begin >= 1 and (probe.LastPreviewSize.Width, probe.LastPreviewSize.Height) == (100, 50)
    ip.GenerateGCode()
    assert probe.WaitComplete(10000) and probe.LastError is None
    assert make_ip.rig.core.LoadedFile.Count > 0
    ip.Resume()  # already running: nothing


@pytest.mark.parametrize("tool,options", [
    ("Line2Line", {"LinePreview": True, "LineDirection": "Vertical"}),
    ("Dithering", {"LinePreview": True, "LineDirection": "NewDiagonalGrid"}),
    ("Vectorize", {"FillingDirection": "NewCross"}),
    ("Vectorize", {"FillingDirection": "None"}),
    ("NoProcessing", {}),
    ("Centerline", {}),
])
def test_preview_runs_for_every_tool(make_ip, probe, tool, options):
    ip = make_ip(GRAD, options={"SelectedTool": tool, **options})
    ip.Resume()
    assert probe.WaitReady(10000)


def test_demo_preview_shows_the_white_point(make_ip, probe):
    ip = make_ip(GRAD, options={"Demo": True})
    ip.Resume()
    assert probe.WaitReady(10000)


def test_changing_a_property_while_running_restarts_the_preview(make_ip, probe):
    ip = make_ip(GRAD)
    ip.Resume()
    assert probe.WaitReady(10000)
    probe.ResetReady()
    for v in (10, 20, 30, 40):  # each change aborts the previous preview thread
        ip.Threshold = v
    assert probe.WaitReady(10000)
    assert probe.Begin >= 2
    ip.Suspend()
    ip.Dispose()
