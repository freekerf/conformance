"""Differential layer (opt-in, ``make test-diff``): the C# host and FreeKerf run on the
same generated inputs and their outputs are compared. Needs the Mono build of
LaserGRBL and ``FREEKERF_BIN``; skipped unless ``FREEKERF_DIFF=1``.

Differences explained by an entry of FreeKerf's ``doc/divergences.md`` are removed
by the rules in ``lasergrbl_harness.differential.RULES`` (one function per DIV id);
nothing else may be normalized."""

from __future__ import annotations

import os
import shutil

import pytest

ENABLED = os.environ.get("FREEKERF_DIFF") == "1"

if not ENABLED:
    collect_ignore_glob = ["test_*.py"]
else:
    from lasergrbl_harness import bootstrap
    from lasergrbl_harness.host import freekerf_bin

    if shutil.which(freekerf_bin()) is None:
        raise pytest.UsageError(f"FREEKERF_BIN={freekerf_bin()!r} not found")
    bootstrap.load_csharp()


@pytest.fixture(autouse=True)
def _csharp_state():
    from lasergrbl_harness import bootstrap

    bootstrap.reset_csharp_state()
    yield
