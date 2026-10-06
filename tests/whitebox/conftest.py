"""White-box layer: the C# core loaded in-process through pythonnet."""

from __future__ import annotations

import pytest

from lasergrbl_harness import bootstrap

bootstrap.load_csharp()


@pytest.fixture(autouse=True)
def _isolated_core_state():
    bootstrap.reset_csharp_state()
    yield
    bootstrap.restore_csv()


@pytest.fixture
def rigs():
    """Factory for CoreRig instances; every rig is closed (threads stopped) at teardown."""
    from lasergrbl_harness.core_rig import CoreRig

    made = []

    def make(*args, **kwargs):
        r = CoreRig(*args, **kwargs)
        made.append(r)
        return r

    yield make
    for r in made:
        r.close()


@pytest.fixture
def rig(rigs):
    return rigs()
