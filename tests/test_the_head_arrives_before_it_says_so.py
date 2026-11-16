"""A long move of the SPIM head is not reported done while it is still going.

Seen twice on the rig in one day: "Axis move to 1000.00 did not complete
cleanly ... Wait for device ZStage:V:37 timed out after 5000ms". The core
stops waiting after five seconds; the head takes longer than that over a few
hundred micrometres. The timeout was taken as the move having failed, and the
page was told where the head was at that moment, while it went on moving.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "lightsheet_side_param", Path(__file__).with_name("test_lightsheet_side_param.py")
)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from gently.exceptions import HardwareError  # noqa: E402
from gently.hardware.dispim.devices.piezo import DiSPIMFDrive  # noqa: E402


class Core:
    """A head that is still moving for the first two waits."""

    def __init__(self, timeouts: int, then: Exception | None = None):
        self.timeouts, self.then, self.waits, self.sent = timeouts, then, 0, None

    def setPosition(self, name, position):
        self.sent = position

    def waitForDevice(self, name):
        self.waits += 1
        if self.waits <= self.timeouts:
            raise RuntimeError(f'Wait for device "{name}" timed out after 5000ms')
        if self.then is not None:
            raise self.then

    def getPosition(self, name):
        raise RuntimeError("no answer")


def _move(core, timeout_s=120.0):
    head = DiSPIMFDrive("ZStage:V:37", core, move_timeout_s=timeout_s)
    status = head.set(1000.0)
    for t in threading.enumerate():
        if t is not threading.current_thread():
            t.join(timeout=5)
    return head, status


def test_a_wait_that_timed_out_is_waited_again():
    core = Core(timeouts=2)
    _, status = _move(core)
    assert core.sent == 1000.0 and core.waits == 3
    assert status.done and status.success


def test_any_other_failure_is_still_a_failure_and_so_is_running_out_of_time():
    _, status = _move(Core(timeouts=0, then=RuntimeError("Serial command failed")))
    assert "Serial command failed" in str(status.exception(timeout=1))
    # A head that never stops: the move's own time, not for ever.
    _, status = _move(Core(timeouts=10**9), timeout_s=0.0)
    assert status.exception(timeout=1) is not None and not status.success


def test_a_height_that_cannot_be_read_says_so():
    head = DiSPIMFDrive("ZStage:V:37", Core(timeouts=0))
    with pytest.raises(HardwareError, match="could not read ZStage:V:37"):
        head.read()
