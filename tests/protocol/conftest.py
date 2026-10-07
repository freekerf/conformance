"""Black-box protocol layer: a host (selected by LASERGRBL_HOST, default the C# core)
opens a PTY behind which a fake Grbl 1.1 device records the wire traffic.

Nothing here touches host internals: tests use the HostAdapter API and the device."""

from __future__ import annotations

import os

import pytest

from lasergrbl_harness.fake_grbl import FakeGrbl
from lasergrbl_harness.host import make_host, wait
from lasergrbl_harness.jobs import forget_traffic, settle
from lasergrbl_harness.links import PtyLink, hang_up_all

CSHARP = os.environ.get("LASERGRBL_HOST", "csharp") == "csharp"

if CSHARP:
    from lasergrbl_harness import bootstrap

    bootstrap.load_csharp()


@pytest.fixture(autouse=True)
def _host_state():
    if CSHARP:
        from lasergrbl_harness import bootstrap

        bootstrap.reset_csharp_state()
    yield


@pytest.fixture
def device():
    return FakeGrbl()


@pytest.fixture
def pty(device):
    link = PtyLink(device)
    yield link
    link.close()


@pytest.fixture
def host():
    h = make_host()
    yield h
    hang_up_all()  # first, so the host's serial reader is not left blocked in poll()
    h.close()


@pytest.fixture
def connected(host, pty, device):
    """Host connected to the device and done with its connect-time queries."""
    host.connect(pty.path)
    wait(lambda: host.connected, 10, "host did not connect")
    wait(lambda: "$$" in device.lines and "$I" in device.lines, 10, "no $$/$I after connect")
    wait(lambda: device.pending_lines == 0 and host.ready and host.status == "Idle", 10)
    device.lines.clear()
    device.realtime.clear()
    device.max_rx_used = 0
    return host


@pytest.fixture
def job(tmp_path):
    def make(lines, name="job.nc"):
        p = tmp_path / name
        p.write_text("\n".join(lines) + "\n")
        return str(p)

    return make


@pytest.fixture
def board(host):
    """Factory: a FakeGrbl built with ``kwargs`` behind its own PTY, the host connected
    to it and settled (connect-time queries answered, Idle). Returns the device."""
    links = []

    def make(settle_host=True, **kwargs):
        dev = FakeGrbl(**kwargs)
        link = PtyLink(dev)
        links.append(link)
        dev.link = link
        host.connect(link.path)
        if settle_host:
            settle(host, dev)
            forget_traffic(dev)
        return dev

    yield make
    for link in links:
        link.close()  # hang up first so the host's serial reader wakes up


@pytest.fixture
def classic(board):
    """A board that does not advertise its buffer (no Bf: field, OPT says 127):
    the host must stay within the classic 127 bytes."""
    return board(report_buffer=False, opt_line="[OPT:V,15,127]")
