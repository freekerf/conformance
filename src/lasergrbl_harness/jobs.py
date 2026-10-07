"""Shared vocabulary of the protocol tests: default header/footer on the wire,
synthetic job lines and small waits on the device + host pair."""

from __future__ import annotations

from .host import wait

HEADER = "G90"  # default header "G90 (use absolute coordinates)" with the comment stripped
FOOTER = "G0X0Y0Z0"  # default footer "G0 X0 Y0 Z0 (move back to origin)"
PASSES = ["", "", "", ""]  # default passes code: four comment-only lines (FINDINGS.md F-17)


def job_lines(n, start=0):
    return [f"G1 X{i % 50}.{i % 10} Y{(i * 7) % 40} F{1000 + i}" for i in range(start, start + n)]


def wire(line):
    return line.replace(" ", "")


def next_fits(device, expected, budget):
    """True while the next expected line would still fit in ``budget`` bytes."""
    i = len(device.lines)
    return i < len(expected) and device.rx_used + len(expected[i]) + 1 <= budget


def settle(host, device):
    """Connected, connect-time queries answered, and the last status report is Idle."""
    wait(lambda: "$I" in device.lines and device.pending_lines == 0 and host.ready and host.status == "Idle", 10)


def forget_traffic(device):
    """Start the wire record from here (keeps the device state)."""
    device.lines.clear()
    device.realtime.clear()
    device.raw.clear()
    device.max_rx_used = 0
