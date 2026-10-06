"""White-box tests of the importers (G-code generators, SVG/DXF import, Line2Line
raster, image transformations): the parts the golden cases cannot reach well
(errors, truth tables, internal helpers, settings persistence)."""

from __future__ import annotations

import pytest

from lasergrbl_harness import bootstrap

bootstrap.load_csharp()


@pytest.fixture(autouse=True)
def _isolated_state():
    from lasergrbl_harness import importers

    bootstrap.reset_csharp_state()
    importers.configure_machine()
    importers.reset_gcode_statics()
    importers.set_gcode_firmware("Grbl")
    yield
