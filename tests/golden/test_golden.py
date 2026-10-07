"""Every fixtures/gcode/*.nc must analyze and stream exactly as recorded in
fixtures/golden/<name>.json. Regenerate with ``make golden`` (pytest --update-golden)
after an intentional behaviour change, and review the diff."""

import json
import re
from pathlib import Path

import pytest

from lasergrbl_harness.golden import analyze

ROOT = Path(__file__).resolve().parents[2]
INPUTS = sorted((ROOT / "fixtures" / "gcode").glob("*.nc"))
GOLDEN = ROOT / "fixtures" / "golden"


def _case(src):
    """A first line ``; rust_divergence: DIV-NNN`` marks a case where FreeKerf
    intentionally differs (see tests/conftest.py)."""
    first = src.read_text(encoding="utf-8").splitlines()[0] if src.stat().st_size else ""
    m = re.match(r";\s*rust_divergence:\s*(DIV-\d+)", first)
    marks = [pytest.mark.rust_divergence(m.group(1))] if m else []
    return pytest.param(src, marks=marks, id=src.stem)


@pytest.mark.parametrize("src", [_case(p) for p in INPUTS])
def test_golden(src, request):
    got = analyze(str(src))
    target = GOLDEN / (src.stem + ".json")
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(got, indent=1) + "\n")
        return
    assert target.exists(), f"missing {target.name}: run `make golden`"
    expected = json.loads(target.read_text())
    for key in expected:
        assert got.get(key) == expected[key], f"{src.name}: '{key}' differs"
    assert set(got) == set(expected)


def test_every_golden_file_has_an_input():
    names = {p.stem for p in INPUTS}
    orphans = [p.name for p in GOLDEN.glob("*.json") if p.stem not in names]
    assert not orphans
