"""Protocol, C# vs FreeKerf: generated scenarios (device behaviour, host options,
operations) played on each host; per operation the device traffic and the coarse
host state must be equal after the documented divergences are normalized."""

import os

import pytest
from hypothesis import HealthCheck, given, note, settings

from lasergrbl_harness.differential import normalize, play, protocol_scenario

# every generated example runs inside this one test
pytestmark = pytest.mark.timeout(4 * 3600)

EXAMPLES = int(os.environ.get("DIFF_PROTOCOL_EXAMPLES", "25"))
COMPARED = ["lines", "realtime", "rx_within_buffer", "rx_fill", "overflows", "error", "status", "job_running",
            "job_errors", "issues", "buffer_size"]


@settings(max_examples=EXAMPLES, deadline=None, suppress_health_check=[HealthCheck.too_slow], print_blob=True)
@given(scenario=protocol_scenario())
def test_wire_and_states_are_the_same(scenario, tmp_path_factory):
    note(f"scenario: {scenario!r}")
    cs = [normalize(t, "csharp") for t in play("csharp", scenario, tmp_path_factory.mktemp("cs"))]
    rs = [normalize(t, "rust") for t in play("rust", scenario, tmp_path_factory.mktemp("rs"))]
    for a, b in zip(cs, rs):
        for key in COMPARED:
            assert a[key] == b[key], f"after {a['op']!r}: {key}: C# {a[key]!r} != FreeKerf {b[key]!r}"
