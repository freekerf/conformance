"""Bounded waits on conditions (never blind sleeps).

The C# core exposes no thread-safe notification we can subscribe to from Python
without a WinForms message loop, so host-side conditions are polled with a short
interval until they hold or the timeout expires (then the test fails loudly).
Device-side conditions use ``FakeGrbl.wait_for`` (a real condition variable).
"""

from __future__ import annotations

import time


def wait_until(predicate, timeout: float = 5.0, interval: float = 0.002, message: str = "") -> None:
    deadline = time.monotonic() + timeout
    while True:
        if predicate():
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(message or f"condition not met within {timeout}s")
        time.sleep(interval)


def stays_true(predicate, duration: float, interval: float = 0.005) -> bool:
    """Checks that ``predicate`` holds for the whole ``duration`` (used to assert that
    something does *not* happen, e.g. the host does not send while the buffer is full)."""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        if not predicate():
            return False
        time.sleep(interval)
    return predicate()
