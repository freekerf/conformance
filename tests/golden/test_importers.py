"""Every fixtures/importers/cases/*.json must produce exactly what is recorded in
fixtures/golden/importers/<name>.json (G-code generators, Hershey text, SVG/DXF
import, Line2Line raster, image transformations). Regenerate with ``make golden``
after an intentional behaviour change, and review the diff. Case format:
``lasergrbl_harness/importers.py``."""

import json
import os
import re
from pathlib import Path

import pytest

from lasergrbl_harness.importers import load_cases, run_case, rust_kinds
from lasergrbl_harness.tolerance import gcode_within_tolerance, pixels_within_tolerance, summary_within_tolerance

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden" / "importers"
CASES = load_cases()
RUST = os.environ.get("LASERGRBL_HOST", "csharp") == "rust"


def _comparable(case, key, value):
    """FreeKerf has no intermediate converter text: the Rust host is compared on the
    ``converter_output`` of ``svg_text`` cases without its ``(...)`` comments, which
    LaserGRBL removes when it loads the lines (FreeKerf's DIV-106). Everything else is
    compared as it is, and the C# host always is."""
    if RUST and case["kind"] == "svg_text" and key == "converter_output":
        return [re.sub(r"\([^)]*\)", "", line) for line in value]
    return value


def _case(name, case):
    """``"rust_divergence": "DIV-NNN"`` in a case marks an intentional FreeKerf
    difference (see tests/conftest.py); the C# host runs the case unchanged."""
    marks = [pytest.mark.rust_divergence(case["rust_divergence"])] if "rust_divergence" in case else []
    return pytest.param(name, case, marks=marks, id=name)


def _cell(case):
    """Burn map cell of a case, mm: one dot of its finest resolution (dots/mm)."""
    conf = case.get("conf", {})
    return 1.0 / max(float(conf.get("res", 10.0)), float(conf.get("fres", 10.0)))


def _harness_state(case, key, expected):
    """Fields that are harness state, not LaserGRBL output, for the Rust host: when
    an ``image_processor`` generation fails, ``summary`` describes the loaded file
    LaserGRBL left untouched (the core's default file, whose range is the table);
    ``import-case`` has no loaded file. ``gcode`` and ``generation_error`` are still
    compared."""
    return RUST and case["kind"] == "image_processor" and key == "summary" and expected.get("generation_error")


def _matches(case, key, got, expected):
    """Exact, except for the Rust host on ``platform_dependent`` cases: those goldens
    are libgdiplus drawings (bitmaps, or G-code engraved from them), compared within
    the tolerance of FreeKerf ADR 0008 (``lasergrbl_harness.tolerance``)."""
    if RUST and "platform_dependent" in case:
        if key == "pixels":
            return pixels_within_tolerance(got, expected)
        if key == "gcode":
            return gcode_within_tolerance(got, expected, _cell(case))
        if key == "summary":
            return summary_within_tolerance(got, expected, _cell(case))
    return _comparable(case, key, got) == _comparable(case, key, expected)


@pytest.mark.parametrize("name,case", [_case(n, c) for n, c in CASES])
def test_importer_golden(name, case, request):
    if RUST and case["kind"] not in rust_kinds():
        pytest.skip(f"FreeKerf does not run '{case['kind']}' cases yet")
    got = run_case(case)
    target = GOLDEN / (name + ".json")
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(got, indent=1) + "\n")
        return
    assert target.exists(), f"missing {target.name}: run `make golden`"
    expected = json.loads(target.read_text())
    for key in expected:
        if _harness_state(case, key, expected):
            continue
        assert _matches(case, key, got.get(key), expected[key]), f"{name}: '{key}' differs"
    assert set(got) == set(expected)


def test_every_importer_golden_has_a_case():
    names = {n for n, _ in CASES}
    orphans = [p.name for p in GOLDEN.glob("*.json") if p.stem not in names]
    assert not orphans
