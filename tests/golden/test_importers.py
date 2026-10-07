"""Every fixtures/importers/cases/*.json must produce exactly what is recorded in
fixtures/golden/importers/<name>.json (G-code generators, Hershey text, SVG/DXF
import, Line2Line raster, image transformations). Regenerate with ``make golden``
after an intentional behaviour change, and review the diff. Case format:
``lasergrbl_harness/importers.py``."""

import json
import os
from pathlib import Path

import pytest

from lasergrbl_harness.importers import load_cases, run_case

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "fixtures" / "golden" / "importers"
CASES = load_cases()


@pytest.mark.skipif(os.environ.get("LASERGRBL_HOST", "csharp") == "rust",
                    reason="FreeKerf's importers come with its milestone M2")
@pytest.mark.parametrize("name,case", CASES, ids=[n for n, _ in CASES])
def test_importer_golden(name, case, request):
    got = run_case(case)
    target = GOLDEN / (name + ".json")
    if request.config.getoption("--update-golden"):
        GOLDEN.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(got, indent=1) + "\n")
        return
    assert target.exists(), f"missing {target.name}: run `make golden`"
    expected = json.loads(target.read_text())
    for key in expected:
        assert got.get(key) == expected[key], f"{name}: '{key}' differs"
    assert set(got) == set(expected)


def test_every_importer_golden_has_a_case():
    names = {n for n, _ in CASES}
    orphans = [p.name for p in GOLDEN.glob("*.json") if p.stem not in names]
    assert not orphans
