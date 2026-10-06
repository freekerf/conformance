"""Suite-wide options and process exit handling (layer-specific setup lives in each
layer's conftest.py; the C# runtime is only started by layers that use it)."""

from __future__ import annotations

import os
import sys

import pytest


def pytest_addoption(parser):
    parser.addoption("--update-golden", action="store_true", help="rewrite fixtures/golden/*.json from the current host behaviour")


def pytest_sessionfinish(session, exitstatus):
    session.config._lasergrbl_exitstatus = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    from lasergrbl_harness import runtime

    if not runtime.is_loaded():
        return
    # Tearing down an embedded Mono that ran our code deadlocks in mono_jit_cleanup;
    # nothing useful happens after this point, so flush coverage and leave without
    # the CLR shutdown. See README "Known issues".
    if runtime.coverage_enabled():
        runtime.flush_coverage()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(getattr(config, "_lasergrbl_exitstatus", 0))
