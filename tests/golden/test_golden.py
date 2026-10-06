"""Every fixtures/gcode/*.nc must analyze and stream exactly as recorded in
fixtures/golden/<name>.json. Regenerate with ``make golden`` (pytest --update-golden)
after an intentional behaviour change, and review the diff."""

import json
from pathlib import Path

import pytest

from lasergrbl_harness.golden import analyze

ROOT = Path(__file__).resolve().parents[2]
INPUTS = sorted((ROOT / "fixtures" / "gcode").glob("*.nc"))
GOLDEN = ROOT / "fixtures" / "golden"


@pytest.mark.parametrize("src", INPUTS, ids=[p.stem for p in INPUTS])
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
