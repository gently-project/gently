"""From an audit of what an overnight run can lose: light that stays on, and
stacks that are imaged and not kept.

- HALT stopped what moves and left what shines.
- A stack whose camera call never returned held the lasers on.
- An error raised while saving a stack (a full disk) was counted and never
  stopped the embryo: imaged every round, nothing saved.
- A stack already on disk under a timepoint was deleted for a new one.
- Side B failing threw away side A's stack of the same round.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("aiohttp")

_spec = importlib.util.spec_from_file_location(
    "lightsheet_side_param", Path(__file__).with_name("test_lightsheet_side_param.py")
)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from gently.app.orchestration.timelapse import TimelapseOrchestrator  # noqa: E402
from gently.core.file_store import FileStore  # noqa: E402
from gently.hardware.dispim.device_layer import DeviceLayerServer  # noqa: E402
from gently.hardware.dispim.devices import acquisition  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def _halt(devices: dict, core) -> tuple[int, dict]:
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.system = SimpleNamespace(core=core)
    dl.devices = devices
    resp = asyncio.run(dl.handle_halt_motion(None))
    return resp.status, json.loads(resp.text)


def test_halt_puts_out_everything_that_lights_the_sample():
    core = MagicMock()
    core.isSequenceRunning.return_value = True
    scanner, scanner_b, led = MagicMock(), MagicMock(), MagicMock()
    scanner.name, scanner_b.name = "Scanner:AB", "Scanner:CD"
    lasers = SimpleNamespace(group_name="Laser")
    status, body = _halt(
        {
            "xy_stage": SimpleNamespace(name="XY"),
            "scanner": scanner,
            "scanner_b": scanner_b,
            "laser_control": lasers,
            "led": led,
        },
        core,
    )
    assert status == 200 and body["halted"] == ["xy_stage"]
    # The lasers and the LED first: they are the light.
    assert body["dark"] == [
        "lasers",
        "led",
        "scanner scan",
        "scanner beam",
        "scanner_b scan",
        "scanner_b beam",
        "camera (stopping)",
    ]
    core.setConfig.assert_called_once_with("Laser", "ALL OFF")
    led.set.assert_called_once_with("Closed")
    # The scan and the beams are told without waiting for the card to say it
    # is done: the device's own setters wait, five seconds at a time, and on
    # the rig that was a minute with a stack in flight.
    for name in ("Scanner:AB", "Scanner:CD"):
        core.setProperty.assert_any_call(name, "SPIMState", "Idle")
        core.setProperty.assert_any_call(name, "BeamEnabled", "No")
    scanner.set_spim_state.assert_not_called()
    core.waitForDevice.assert_not_called()
    # Light before motion, and the camera last and not waited for: its stop
    # took a minute on the rig with the scan idle, and the stages had waited.
    order = [c[0] for c in core.method_calls]
    # The lasers, then what moves, then the scan and the beams, then the camera.
    assert (
        order.index("setConfig")
        < order.index("stop")
        < order.index("setProperty")
        < order.index("isSequenceRunning")
    )
    for th in threading.enumerate():
        if th.name == "halt-camera":
            th.join(timeout=5)
    core.stopSequenceAcquisition.assert_called_once()


def test_what_would_not_go_out_is_named_and_the_rest_is_still_tried():
    core = MagicMock()
    core.setConfig.side_effect = RuntimeError("no answer from the laser")
    led = MagicMock()
    status, body = _halt({"laser_control": SimpleNamespace(group_name="Laser"), "led": led}, core)
    assert status == 502 and body["errors"] == {"lasers": "no answer from the laser"}
    assert "led" in body["dark"]
    led.set.assert_called_once_with("Closed")


def test_a_stack_cannot_hold_the_lasers_on():
    core = MagicMock()
    watch = acquisition._lasers_out_after(core, "Laser", 0.05)
    time.sleep(0.3)
    core.setConfig.assert_called_once_with("Laser", "ALL OFF")
    watch.cancel()

    # A stack that ends the ordinary way cancels it, and it does nothing.
    core = MagicMock()
    acquisition._lasers_out_after(core, "Laser", 0.2).cancel()
    time.sleep(0.4)
    core.setConfig.assert_not_called()

    # Both ways of taking a stack start one, and cancel it whatever happened.
    src = Path(acquisition.__file__).read_text(encoding="utf-8")
    assert src.count("watch = _lasers_out_after(") == 2
    assert src.count("            finally:\n                watch.cancel()") == 2


def test_three_failed_rounds_end_the_embryo_whatever_raised_them():
    state = SimpleNamespace(
        error_count=2, last_error="x", is_complete=False, completion_reason=None
    )
    TimelapseOrchestrator._stop_after_errors(state)
    assert state.is_complete is False
    state.error_count, state.last_error = 3, "[Errno 28] No space left on device"
    TimelapseOrchestrator._stop_after_errors(state)
    assert state.is_complete is True
    assert state.completion_reason == "errors: [Errno 28] No space left on device"

    # The branch an exception lands in applies it: it only counted before.
    run = (REPO / "gently/app/orchestration/timelapse.py").read_text(encoding="utf-8")
    raised = run[
        run.index("        except Exception as e:\n            embryo_state.error_count += 1") :
    ]
    raised = raised[: raised.index("self.global_error_log.log_error(")]
    assert "self._stop_after_errors(embryo_state)" in raised


def test_side_b_failing_keeps_side_a():
    run = (REPO / "gently/app/orchestration/timelapse.py").read_text(encoding="utf-8")
    block = run[
        run.index("                    # Full 3D volume (default)\n                    try:") :
    ]
    block = block[: block.index("num_frames = embryo.num_slices")]
    assert (
        'if not (results.get("A") or {}).get("success"):\n                            raise'
        in block
    )
    assert 'results[side] = {"success": False, "error": str(exc)}' in block


def test_a_stack_already_on_disk_is_moved_aside_not_written_over(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("s1", name="night")
    store.register_embryo("s1", "embryo_1")
    first = np.full((2, 4, 4), 7, dtype=np.uint16)
    second = np.full((2, 4, 4), 9, dtype=np.uint16)
    path = store.put_volume("s1", "embryo_1", 3, first)
    again = store.put_volume("s1", "embryo_1", 3, second)
    assert again == path

    import tifffile

    kept = sorted(path.parent.glob("t0003.was_*.tif"))
    assert len(kept) == 1 and (tifffile.imread(kept[0]) == 7).all()
    assert (tifffile.imread(path) == 9).all()
    assert len(list(path.parent.glob("t0003.was_*.meta.yaml"))) == 1

    # The path a stack takes when the instrument has already written it.
    incoming = tmp_path / "incoming.tif"
    tifffile.imwrite(incoming, np.full((2, 4, 4), 11, dtype=np.uint16))
    store.register_volume("s1", "embryo_1", 3, incoming_path=incoming)
    assert len(list(path.parent.glob("t0003.was_*.tif"))) == 2
    assert (tifffile.imread(path) == 11).all()


def test_a_camera_that_never_answers_does_not_keep_the_lasers_on(monkeypatch):
    """The whole path, with a real hang: the stack's own thread is stuck in
    a call to the camera that never returns, so nothing it would do next
    runs. The lasers are put out all the same, from the other thread."""
    import threading

    from gently.hardware.dispim.devices.acquisition import DiSPIMVolumeScanner

    monkeypatch.setattr(acquisition, "LASERS_ON_AT_MOST_S", 0.3)
    stuck = threading.Event()
    presets: list[str] = []

    class Core:
        def setConfig(self, group, preset):
            presets.append(preset)

        def popNextImage(self):
            stuck.wait(20)  # the camera never answers
            raise RuntimeError("released by the test")

        def getRemainingImageCount(self):
            return 1

        def isSequenceRunning(self, *a):
            return False

        def getBufferTotalCapacity(self):
            return 1000

        def __getattr__(self, name):
            return lambda *a, **k: None

    lasers = SimpleNamespace(group_name="Laser", set_power_pct=lambda *a: None)
    vs = DiSPIMVolumeScanner(
        scanner=MagicMock(),
        camera=MagicMock(),
        piezo=MagicMock(),
        laser_control=lasers,
        core=Core(),
    )
    vs.configure(
        num_slices=2,
        exposure_ms=10.0,
        galvo_amplitude=0.5,
        galvo_center=0.0,
        piezo_amplitude=25.0,
        piezo_center=50.0,
    )
    vs.trigger()
    try:
        time.sleep(1.0)
        # Still stuck in the camera, and the lasers are already out.
        assert not stuck.is_set()
        assert presets[0] != "ALL OFF" and "ALL OFF" in presets
    finally:
        stuck.set()


def test_halt_is_heard_while_a_plan_is_running():
    """On the rig, HALT pressed 2.6 s into a five-second stack was acted on at
    7.4 s, after the last frame: a plan runs on the thread that answers
    every request. The stop line is a second listener on its own thread."""
    import http.client
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free = probe.getsockname()[1]
    core = MagicMock()
    core.isSequenceRunning.return_value = False
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.system = SimpleNamespace(core=core)
    dl.devices = {"xy_stage": SimpleNamespace(name="XY"), "led": MagicMock()}
    dl.port = free - 1
    assert dl.start_stop_line() == free
    try:
        # Nothing else of the device layer is running: no event loop at all.
        conn = http.client.HTTPConnection("127.0.0.1", free, timeout=5)
        conn.request("POST", "/halt", body="{}")
        resp = conn.getresponse()
        body = json.loads(resp.read())
        assert resp.status == 200 and body["halted"] == ["xy_stage"] and "led" in body["dark"]
        core.stop.assert_called_once_with("XY")
    finally:
        dl._stop_line.shutdown()
    # It is started with the device layer, and the client asks it first.
    src = Path(acquisition.__file__).parents[1].joinpath("device_layer.py").read_text("utf-8")
    assert "        self.start_stop_line()\n" in src
    client = Path(acquisition.__file__).parents[1].joinpath("client.py").read_text("utf-8")
    halt = client[client.index("    async def halt_motion(self) -> dict:") :][:900]
    assert "int(port) + 1" in halt and 'self._api_post("/api/motion/halt", {})' in halt


def test_a_stack_cut_short_is_a_failure():
    """Stopped part way, a stack was returned as it stood: 140 of 300 slices,
    filed as that timepoint."""
    from gently.hardware.dispim.devices.acquisition import DiSPIMVolumeScanner

    frames = [np.zeros((2, 2), np.uint16)]  # one frame of the three asked for
    core = MagicMock()
    core.isSequenceRunning.return_value = False
    core.getBufferTotalCapacity.return_value = 1000
    core.getRemainingImageCount.side_effect = lambda: len(frames)
    core.popNextImage.side_effect = lambda: frames.pop()
    vs = DiSPIMVolumeScanner(
        scanner=MagicMock(),
        camera=MagicMock(),
        piezo=MagicMock(),
        laser_control=MagicMock(),
        core=core,
    )
    vs.configure(
        num_slices=3,
        exposure_ms=10.0,
        galvo_amplitude=0.5,
        galvo_center=0.0,
        piezo_amplitude=25.0,
        piezo_center=50.0,
    )
    status = vs.trigger()
    import threading

    for t in threading.enumerate():
        if t is not threading.current_thread() and t.name != "stop-line":
            t.join(timeout=5)
    assert "stack cut short: 1 of 3 frames" in str(status.exception(timeout=1))
    assert vs.read() == {}


def test_a_move_stopped_part_way_does_not_say_it_arrived():
    """Seen on the simulated rig: a stage sent to -2200 and halted at 33
    reported success. The plan had ended; the stage had not arrived."""
    from gently.hardware.dispim import client as client_module
    from gently.hardware.dispim.client import DiSPIMMicroscope

    def scope(at):
        c = DiSPIMMicroscope.__new__(DiSPIMMicroscope)

        async def submit(name, kwargs=None, timeout=None):
            return {"success": True}

        async def where():
            return at

        c._submit_plan_and_wait = submit  # type: ignore[method-assign]
        c.get_stage_position = where  # type: ignore[method-assign]
        return c

    got = asyncio.run(scope((33.0, -355.0)).move_to_position(-2200.0, -355.0))
    assert got["success"] is False and got["x"] == 33.0
    assert "2233 µm short of (-2200.0, -355.0)" in got["error"]
    near = client_module.ARRIVED_WITHIN_UM - 1
    got = asyncio.run(scope((-2200.0 + near, -355.0)).move_to_position(-2200.0, -355.0))
    assert got == {"success": True, "x": -2200.0, "y": -355.0}
