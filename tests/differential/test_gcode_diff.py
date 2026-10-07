"""G-code analysis, C# vs FreeKerf, on generated programs (hypothesis).

Every field of the golden JSON must be equal; a counterexample is shrunk by
hypothesis and becomes a fixed golden case (fixtures/gcode/diff_*.nc)."""

import os

import pytest
from hypothesis import HealthCheck, assume, given, note, settings

from lasergrbl_harness.differential import first_difference, gcode_comparable, gcode_program
from lasergrbl_harness.golden import analyze_csharp, analyze_rust

# every generated example runs inside this one test
pytestmark = pytest.mark.timeout(4 * 3600)

EXAMPLES = int(os.environ.get("DIFF_GCODE_EXAMPLES", "300"))


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow], print_blob=True)
@given(text=gcode_program())
def test_analysis_is_the_same(text, tmp_path_factory):
    assume(gcode_comparable(text))  # documented divergences on the input (GCODE_RULES)
    path = tmp_path_factory.mktemp("diff") / "program.nc"
    path.write_bytes(text.encode("utf-8"))
    note(f"program: {text!r}")
    cs = analyze_csharp(str(path))
    rs = analyze_rust(str(path))
    diff = first_difference(cs, rs)
    assert diff is None, f"{diff[0]}[{diff[1]}]: C# {diff[2]!r} != FreeKerf {diff[3]!r}"
