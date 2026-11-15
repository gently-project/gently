"""Both views in one scan, the way the ASIdiSPIM plugin takes them.

"see if you can reduce the time between the two view acquisitions ... also
check how asidispim plugin does it." Measured on the rig, two one-sided
volumes begin 2.4 s apart: 0.8 s is side A's scan, the rest is putting A away
and setting B up. The plugin (ControllerUtils.prepareControllerForAquisition)
sets both sides up first, writes SPIMNumSides=2 and SPIMDelayBeforeSide to the
card, starts both cameras, and sends one trigger.

No rig in CI, so the order of what the hardware is told is pinned here on
stand-ins. That a true stack of each side comes back is for a sample.
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np

_spec = importlib.util.spec_from_file_location(
    "lightsheet_side_param", Path(__file__).with_name("test_lightsheet_side_param.py")
)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from gently.hardware.dispim.client import DiSPIMMicroscope  # noqa: E402
from gently.hardware.dispim.devices.acquisition import (  # noqa: E402
    DiSPIMTwoSidedVolumeScanner,
    DiSPIMVolumeScanner,
)

REPO = Path(__file__).resolve().parents[1]
A = {"galvo_amplitude": 0.4, "galvo_center": 0.1, "piezo_amplitude": 30.0, "piezo_center": 3.0}
B = {"galvo_amplitude": 0.3, "galvo_center": 0.0, "piezo_amplitude": 31.0, "piezo_center": 2.0}


class Core:
    """Enough of a core to scan: frames arrive once the scan is running,
    side A's first, each saying which camera took it."""

    def __init__(self, n: int, named: bool = True, drop: int = 0):
        self.n, self.named = n, named
        self.queue: list[tuple[str, np.ndarray]] = []
        self.log: list[tuple] = []
        self.drop = drop

    def run(self):
        for cam, value in (("HamCam1", 1), ("HamCam2", 2)):
            self.queue += [(cam, np.full((2, 2), value, np.uint16))] * self.n
        if self.drop:
            del self.queue[-self.drop :]

    def getRemainingImageCount(self):
        return len(self.queue)

    def popNextImage(self):
        return self.queue.pop(0)[1]

    def popNextImageMD(self, md):
        if not self.named:
            raise AttributeError("no metadata on this core")
        cam, img = self.queue.pop(0)
        md.cam = cam
        return img

    def isSequenceRunning(self, name=None):
        return False

    def getBufferTotalCapacity(self):
        return 10_000

    def setProperty(self, dev, prop, value):
        self.log.append(("set", dev, prop, value))

    def setConfig(self, group, preset):
        self.log.append(("lasers", preset))

    def startSequenceAcquisition(self, name, n, interval, stop):
        self.log.append(("camera started", name, n))

    def __getattr__(self, name):  # everything else is accepted
        return lambda *a, **k: None


def _pair(core):
    def one(side, cam):
        scanner, camera, piezo = MagicMock(), MagicMock(), MagicMock()
        scanner.name, camera.name = f"Scanner{side}", cam
        lasers = MagicMock()
        lasers.group_name = "Laser"
        vs = DiSPIMVolumeScanner(
            scanner=scanner,
            camera=camera,
            piezo=piezo,
            laser_control=lasers,
            core=core,
            name="volume_scanner" if side == "A" else "volume_scanner_b",
            side=side,
        )
        return vs

    a, b = one("A", "HamCam1"), one("B", "HamCam2")
    a.scanner.set_spim_state.side_effect = lambda s: (
        (core.log.append(("scan", s)), core.run())
        if s == "Running"
        else core.log.append(("scan", s))
    )
    return DiSPIMTwoSidedVolumeScanner(a=a, b=b), a, b


def _scan(ab, monkeypatch, n=3):
    import gently.hardware.dispim.devices.acquisition as acq

    class Md:
        cam = None

        def GetSingleTag(self, _):
            return MagicMock(GetValue=lambda: self.cam)

    monkeypatch.setattr(acq.pymmcore, "Metadata", Md, raising=False)
    ab.configure(num_slices=n, exposure_ms=10.0, side_a=A, side_b=B)
    status = ab.trigger()
    for t in threading.enumerate():
        if t is not threading.current_thread():
            t.join(timeout=10)
    return status


def test_both_sides_are_set_up_before_the_one_trigger(monkeypatch):
    core = Core(3)
    ab, a, b = _pair(core)
    _scan(ab, monkeypatch)

    # Each side with its own fit, B first so the card's first side ends as A.
    assert b.scanner.configure_for_volume_acquisition.call_args.kwargs["galvo_center"] == 0.0
    assert a.scanner.configure_for_volume_acquisition.call_args.kwargs["galvo_center"] == 0.1
    assert b.piezo.configure_for_volume_acquisition.call_args.kwargs["amplitude_um"] == 31.0
    first = a.scanner.configure_spim_parameters.call_args_list[0].kwargs
    assert first == {"num_slices": 3, "num_sides": 2, "first_side": "A"}
    assert ("set", "ScannerA", "SPIMDelayBeforeSide(ms)", 50.0) in core.log

    # Both cameras are waiting before the scan is set running, once.
    order = [e for e in core.log if e[0] in ("camera started", "scan")]
    assert order[:3] == [
        ("camera started", "HamCam1", 3),
        ("camera started", "HamCam2", 3),
        ("scan", "Running"),
    ]
    assert [e for e in core.log if e == ("scan", "Running")] == [("scan", "Running")]
    b.scanner.set_spim_state.assert_not_called()  # one card, one trigger


def test_it_reads_as_a_volume_of_each_side_and_puts_everything_away(monkeypatch):
    core = Core(3)
    ab, a, b = _pair(core)
    _scan(ab, monkeypatch)
    got = ab.read()
    assert list(got) == ["volume_scanner", "volume_scanner_b"]
    assert got["volume_scanner"]["value"].shape == (3, 2, 2)
    assert (got["volume_scanner"]["value"] == 1).all() and (
        got["volume_scanner_b"]["value"] == 2
    ).all()
    assert got["volume_scanner"]["timestamp"] <= got["volume_scanner_b"]["timestamp"]
    # Lasers out last, cameras and piezos back, the card back to one side.
    assert core.log[-1] == ("lasers", "ALL OFF")
    for vs in (a, b):
        vs.camera.set_trigger_mode.assert_called_with("INTERNAL")
        vs.piezo.set_spim_state.assert_called_with("Idle")
    assert a.scanner.configure_spim_parameters.call_args.kwargs["num_sides"] == 1


def test_a_core_that_names_no_camera_gives_the_frames_in_order(monkeypatch):
    core = Core(3, named=False)
    ab, _, _ = _pair(core)
    _scan(ab, monkeypatch)
    got = ab.read()
    assert (got["volume_scanner"]["value"] == 1).all() and (
        got["volume_scanner_b"]["value"] == 2
    ).all()


def test_a_short_stack_is_a_failure_and_the_lasers_still_go_out(monkeypatch):
    import gently.hardware.dispim.devices.acquisition as acq

    quick = SimpleNamespace(timeouts=SimpleNamespace(volume_acquisition=0.3))
    monkeypatch.setattr(acq, "settings", quick)
    core = Core(3, drop=1)
    ab, _, _ = _pair(core)
    status = _scan(ab, monkeypatch)
    assert isinstance(status.exception(timeout=1), TimeoutError)
    assert "3 + 2 of 3 + 3" in str(status.exception())
    assert core.log[-1] == ("lasers", "ALL OFF")
    assert ab.read() == {}


def test_the_client_returns_each_side_with_its_own_time():
    client = DiSPIMMicroscope.__new__(DiSPIMMicroscope)
    seen: dict = {}

    async def fake_submit(name, kwargs, timeout):
        seen.update(kwargs, plan=name)
        event = {
            "data": {
                "volume_scanner": np.ones((2, 3, 4), np.uint16),
                "volume_scanner_b": np.zeros((2, 3, 4), np.uint16),
            },
            "timestamps": {"volume_scanner": 100.0, "volume_scanner_b": 100.84},
        }
        return {"success": True, "documents": {"events": [event]}}

    client._submit_plan_and_wait = fake_submit  # type: ignore[method-assign]
    got = asyncio.run(client.acquire_volume_two_sided(A, B, num_slices=2, laser_power_488_pct=5))
    assert seen["plan"] == "acquire_two_sided_volume_plan"
    assert seen["volume_scanner"] == "volume_scanner_ab" and seen["laser_power_488_pct"] == 5
    assert got["A"]["volume"].all() and not got["B"]["volume"].any()
    assert round(got["B"]["acquired_at_epoch"] - got["A"]["acquired_at_epoch"], 2) == 0.84

    async def failed(name, kwargs, timeout):
        return {"success": False, "error": "timed out"}

    client._submit_plan_and_wait = failed  # type: ignore[method-assign]
    got = asyncio.run(client.acquire_volume_two_sided(A, B))
    assert got["A"] == got["B"] == {"error": "timed out", "success": False}


def test_a_run_uses_it_only_when_asked():
    run = (REPO / "gently/app/orchestration/timelapse.py").read_text(encoding="utf-8")
    assert 'os.environ.get("GENTLY_TWO_SIDES_ONE_SCAN") == "1"' in run
    assert 'and sides == ["A", "B"]' in run
    assert "for side in [] if one_scan else sides:" in run
