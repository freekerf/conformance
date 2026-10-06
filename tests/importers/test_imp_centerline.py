"""Centerline: GrblFile.LoadImageCenterline and the Autotrace wrapper, with the
autotrace test double (importers.fake_autotrace) standing in for autotrace.exe.
Whole conversions are golden (fixtures/importers/cases/centerline_*.json)."""

import os

import pytest

import LaserGRBL
from LaserGRBL import Autotrace, GrblFile

from lasergrbl_harness import clr_util as cu
from lasergrbl_harness import importers as im
from lasergrbl_harness.core_rig import wait_loaded
from LaserGRBLTests import GrblFileEvents

IMG = {"ascii": ["....", ".##.", "...."]}
SVG = im.INPUTS / "svg" / "autotrace_out.svg"


def conf():
    c = GrblFile.L2LConf()
    for k, v in im.L2L_DEFAULTS.items():
        if k == "dir":
            v = getattr(LaserGRBL.RasterConverter.ImageProcessor.Direction, v)
        elif k == "firmwareType":
            v = getattr(LaserGRBL.Firmware, v)
        setattr(c, k, v)
    return c


def centerline(f, append=False):
    cu.call(f, "LoadImageCenterline", im.make_bitmap(IMG), "x", True, 110, True, 10, conf(), append, None)


def test_without_autotrace_the_empty_output_fails_as_xml(tmp_path):
    """Here ExePath itself throws (no command line under pythonnet); on Windows a
    missing or failing autotrace.exe gives the same result: the failure is only
    logged, the empty output is parsed as SVG and the XmlException escapes
    LoadImageCenterline after the file was cleared and OnFileLoading raised (FINDINGS)."""
    f = GrblFile()
    f.LoadFile(str(_nc(tmp_path)), False)
    wait_loaded(f)
    assert f.Count == 1
    ev = GrblFileEvents(f)
    with pytest.raises(Exception) as e:
        centerline(f)
    assert "Root element is missing" in str(e.value)
    assert f.Count == 0 and (ev.Loading, ev.Loaded) == (1, 0)


def test_autotrace_printing_nothing_fails_the_same_way(tmp_path):
    empty = tmp_path / "empty.svg"
    empty.write_text("")
    with im.fake_autotrace(empty, tmp_path):
        with pytest.raises(Exception) as e:
            centerline(GrblFile())
    assert "Root element is missing" in str(e.value)


def test_success_raises_loaded_and_append_keeps_previous_commands(tmp_path):
    f = GrblFile()
    ev = GrblFileEvents(f)
    with im.fake_autotrace(SVG, tmp_path):
        centerline(f)
        first = [str(c.Command) for c in f]
        centerline(f, append=True)
    assert (ev.Loading, ev.Loaded) == (2, 2)
    assert [str(c.Command) for c in f][: len(first)] == first and f.Count == 2 * len(first)
    # comment-only and empty lines of the converter output are dropped
    assert all(str(c.Command).strip() for c in f)


def test_in_use_file_shows_a_message_box(tmp_path):
    f = GrblFile()
    cu.set(f, "InUse", True)
    with pytest.raises(Exception):
        centerline(f)


def test_temp_png_is_written_under_the_data_folder_and_deleted(tmp_path):
    with im.fake_autotrace(SVG, tmp_path) as log:
        Autotrace.BitmapToSvgString(im.make_bitmap(IMG), False, 0, False, 0)
        png = log.read_text().splitlines()[-1]
    assert png.startswith(str(Autotrace.TempPath)) and png.endswith(".png")
    assert not os.path.exists(png)
    assert os.path.isdir(str(Autotrace.TempPath))


def test_svg_document_from_autotrace(tmp_path):
    with im.fake_autotrace(SVG, tmp_path):
        doc = Autotrace.BitmapToSvgDocument(im.make_bitmap(IMG), True, 100, True, 25)
    assert doc.Width.Value == 120 and doc.Height.Value == 80


def test_cleanup_removes_the_temp_folder():
    os.makedirs(str(Autotrace.TempPath), exist_ok=True)
    Autotrace.CleanupTmpFolder()
    assert not os.path.exists(str(Autotrace.TempPath))
    Autotrace.CleanupTmpFolder()  # already gone: nothing happens


def _nc(tmp_path):
    p = tmp_path / "prev.nc"
    p.write_text("G0 X1\n")
    return p
