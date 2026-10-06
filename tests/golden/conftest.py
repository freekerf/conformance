"""Golden layer: input G-code -> analysis/stream snapshots in fixtures/golden/."""

from __future__ import annotations

import os

import pytest

if os.environ.get("LASERGRBL_HOST", "csharp") == "csharp":
    from lasergrbl_harness import bootstrap

    bootstrap.load_csharp()


@pytest.fixture(autouse=True)
def _host_state():
    if os.environ.get("LASERGRBL_HOST", "csharp") == "csharp":
        from lasergrbl_harness import bootstrap

        bootstrap.reset_csharp_state()
    yield
