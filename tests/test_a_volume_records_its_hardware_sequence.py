"""A volume and a brightfield frame record what the hardware did, and when.

"the plot is a feature in gently ui to see the hardware sequences" — and the
records could not draw one. A volume's sidecar kept the embryo's laser
settings and the moment its scan began: not the preset the device routed, not
the power a line with no setting of its own stood at, and not when the lasers
came on, the frames arrived and the lasers went out. A brightfield frame kept
the moment it was filed, after its light was already off.

The device now reports each stack's sequence with its pixels, the client hands
it on, the run writes it beside the volume, and a brightfield frame writes
when its light went on and off.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import yaml

# Patch the hardware stack the way the side-param test does, by loading it.
_spec = importlib.util.spec_from_file_location(
    "lightsheet_side_param", Path(__file__).with_name("test_lightsheet_side_param.py")
)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from gently.app.orchestration.timelapse import TimelapseOrchestrator  # noqa: E402
from gently.app.orchestration.timelapse_models import BfOverview  # noqa: E402
from gently.core.file_store import FileStore  # noqa: E402
from gently.hardware.dispim.client import DiSPIMMicroscope  # noqa: E402
from gently.hardware.dispim.devices.acquisition import (  # noqa: E402
    DiSPIMTwoSidedVolumeScanner,
    DiSPIMVolumeScanner,
)
from gently.harness.state import ExperimentState  # noqa: E402

# A stack's sequence as the device reports it (epoch seconds), and the same
# moments in UTC as they are written to disk — worked out by hand.
SEQ = {
    "laser_config": "488 and 561",
    "lines": [488, 561],
    "powers_pct": {"488": 2.5, "561": 7.5},
    "num_slices": 3,
    "exposure_ms": 20.0,
    "lasers_on": 1794700000.10,
    "scan_started": 1794700000.35,
    "first_frame": 1794700000.40,
    "last_frame": 1794700001.20,
    "lasers_off": 1794700001.30,
}
ON_DISK = {
    "laser_config": "488 and 561",
    "lines": [488, 561],
    "powers_pct": {"488": 2.5, "561": 7.5},
    "num_slices": 3,
    "exposure_ms": 20.0,
    "lasers_on_utc": "2026-11-14T23:46:40.100000Z",
    "scan_started_utc": "2026-11-14T23:46:40.350000Z",
    "first_frame_utc": "2026-11-14T23:46:40.400000Z",
    "last_frame_utc": "2026-11-14T23:46:41.200000Z",
    "lasers_off_utc": "2026-11-14T23:46:41.300000Z",
}


def _join_threads():
    for t in threading.enumerate():
        if t is not threading.current_thread():
            t.join(timeout=5)


def _epoch(utc: str) -> float:
    return datetime.fromisoformat(utc.replace("Z", "+00:00")).timestamp()


# ---- the device ------------------------------------------------------------


def _one_sided(laser_config="488 and 561", readback=None, **powers):
    """A one-sided scanner on a stand-in core that notes when the lasers
    were switched, and three frames waiting once the scan runs."""
    core, scanner = MagicMock(), MagicMock()
    core.isSequenceRunning.return_value = False
    core.getBufferTotalCapacity.return_value = 1000
    frames = [np.zeros((2, 2), np.uint16) for _ in range(3)]
    core.getRemainingImageCount.side_effect = lambda: len(frames)
    core.popNextImage.side_effect = lambda: frames.pop()
    switched: list[tuple[str, float]] = []
    core.waitForConfig.side_effect = lambda group, preset: switched.append((preset, time.time()))
    lasers = MagicMock()
    lasers.group_name = "Laser"
    lasers.get_power_pct.side_effect = readback or (lambda wl: {561: 7.5, 405: 1.0, 637: 3.0}[wl])
    vs = DiSPIMVolumeScanner(
        scanner=scanner, camera=MagicMock(), piezo=MagicMock(), laser_control=lasers, core=core
    )
    vs.configure(
        num_slices=3,
        exposure_ms=20.0,
        galvo_amplitude=0.5,
        galvo_center=0.0,
        piezo_amplitude=25.0,
        piezo_center=50.0,
        laser_config=laser_config,
        **powers,
    )
    vs.trigger()
    _join_threads()
    return vs, lasers, switched


def test_the_device_reports_a_stacks_sequence_with_its_pixels():
    vs, _, switched = _one_sided(laser_power_488_pct=2.5)
    reading = vs.read()
    seq = json.loads(reading[f"{vs.name}_sequence"]["value"])

    on = next(t for preset, t in switched if preset == "488 and 561")
    off = next(t for preset, t in switched if preset == "ALL OFF")
    # Each moment is the hardware's: the lasers are on once their preset is
    # applied, out once ALL OFF is, and the scan and frames come between.
    assert on <= seq["lasers_on"] <= seq["scan_started"]
    assert seq["scan_started"] <= seq["first_frame"] <= seq["last_frame"]
    assert seq["last_frame"] <= off <= seq["lasers_off"]
    # The scan's start is the volume's own time, the one acquired_at keeps.
    assert seq["scan_started"] == reading[vs.name]["timestamp"]
    assert (seq["num_slices"], seq["exposure_ms"]) == (3, 20.0)
    # Bluesky is told of every key a read gives.
    assert vs.describe()[f"{vs.name}_sequence"]["dtype"] == "string"


def test_the_device_reports_the_preset_it_routed_and_each_routed_lines_power():
    vs, lasers, _ = _one_sided(laser_power_488_pct=2.5)
    seq = json.loads(vs.read()[f"{vs.name}_sequence"]["value"])
    assert seq["laser_config"] == "488 and 561"
    assert seq["lines"] == [488, 561]
    # 488 at what it was set to; 561 was given no power, so it ran at its
    # setpoint, read back from the laser.
    assert seq["powers_pct"] == {"488": 2.5, "561": 7.5}
    # A power the device itself set is not read back: a read is a round trip
    # to the laser between the volume's setup and its scan.
    lasers.get_power_pct.assert_called_once_with(561)


def test_a_line_whose_power_cannot_be_read_is_unknown_not_a_failed_volume():
    def serial_timeout(wl):
        raise RuntimeError("serial timeout")

    vs, _, _ = _one_sided("561 only", readback=serial_timeout)
    seq = json.loads(vs.read()[f"{vs.name}_sequence"]["value"])
    assert seq["lines"] == [561]
    assert seq["powers_pct"] == {"561": None}


class _Core:
    """Enough of a core for both sides in one scan: side A's frames, then B's,
    arriving once the scan runs, each naming its camera."""

    def __init__(self, n):
        self.n = n
        self.queue: list[tuple[str, np.ndarray]] = []
        self.switched: list[tuple[str, float]] = []

    def run(self):
        for cam in ("HamCam1", "HamCam2"):
            self.queue += [(cam, np.zeros((2, 2), np.uint16))] * self.n

    def getRemainingImageCount(self):
        return len(self.queue)

    def popNextImageMD(self, md):
        cam, img = self.queue.pop(0)
        md.cam = cam
        return img

    def isSequenceRunning(self, name=None):
        return False

    def getBufferTotalCapacity(self):
        return 10_000

    def waitForConfig(self, group, preset):
        self.switched.append((preset, time.time()))

    def __getattr__(self, name):
        return lambda *a, **k: None


def test_both_sides_in_one_scan_each_report_their_own_frames(monkeypatch):
    import gently.hardware.dispim.devices.acquisition as acq

    class Md:
        cam = None

        def GetSingleTag(self, _):
            return MagicMock(GetValue=lambda: self.cam)

    monkeypatch.setattr(acq.pymmcore, "Metadata", Md, raising=False)
    core = _Core(3)

    def one(side, cam):
        scanner, camera = MagicMock(), MagicMock()
        scanner.name, camera.name = f"Scanner{side}", cam
        lasers = MagicMock()
        lasers.group_name = "Laser"
        lasers.get_power_pct.side_effect = lambda wl: 7.5
        return DiSPIMVolumeScanner(
            scanner=scanner,
            camera=camera,
            piezo=MagicMock(),
            laser_control=lasers,
            core=core,
            name="volume_scanner" if side == "A" else "volume_scanner_b",
            side=side,
        )

    a, b = one("A", "HamCam1"), one("B", "HamCam2")
    a.scanner.set_spim_state.side_effect = lambda s: core.run() if s == "Running" else None
    ab = DiSPIMTwoSidedVolumeScanner(a=a, b=b)
    cal = {
        "galvo_amplitude": 0.4,
        "galvo_center": 0.1,
        "piezo_amplitude": 30.0,
        "piezo_center": 3.0,
    }
    ab.configure(num_slices=3, exposure_ms=10.0, side_a=cal, side_b=cal, laser_power_488_pct=3.0)
    ab.trigger()
    _join_threads()

    reading = ab.read()
    sa = json.loads(reading["volume_scanner_sequence"]["value"])
    sb = json.loads(reading["volume_scanner_b_sequence"]["value"])
    # One preset, one laser window and one scan for the pair; frames each side's.
    assert sa["lasers_on"] == sb["lasers_on"] and sa["lasers_off"] == sb["lasers_off"]
    assert sa["scan_started"] == sb["scan_started"]
    assert sa["first_frame"] <= sa["last_frame"] <= sb["first_frame"] <= sb["last_frame"]
    assert sb["last_frame"] <= sb["lasers_off"]
    # Each side's stack begins when the card turns to it: A at the trigger, B
    # as much later as its first frame came after A's.
    assert sa["side_began"] == sa["scan_started"]
    assert sb["side_began"] == sa["scan_started"] + (sb["first_frame"] - sa["first_frame"])
    assert sa["powers_pct"] == {"488": 3.0, "561": 7.5}
    assert set(ab.describe()) == set(reading)


# ---- the client ------------------------------------------------------------


def _client(event):
    client = DiSPIMMicroscope.__new__(DiSPIMMicroscope)

    async def fake_submit(name, kwargs, timeout=None):
        return {"success": True, "documents": {"events": [event]}}

    client._submit_plan_and_wait = fake_submit  # type: ignore[method-assign]
    return client


def test_the_client_hands_the_sequence_on_with_the_volume():
    client = _client(
        {
            "data": {
                "volume_scanner": np.zeros((3, 2, 2), np.uint16),
                "volume_scanner_sequence": json.dumps(SEQ),
            },
            "timestamps": {"volume_scanner": SEQ["scan_started"]},
        }
    )
    got = asyncio.run(client.acquire_volume(num_slices=3))
    assert got["success"] and got["sequence"] == SEQ


def test_the_client_hands_each_side_its_own_sequence():
    seq_b = {**SEQ, "first_frame": 1794700001.25, "last_frame": 1794700002.0}
    client = _client(
        {
            "data": {
                "volume_scanner": np.zeros((3, 2, 2), np.uint16),
                "volume_scanner_b": np.zeros((3, 2, 2), np.uint16),
                "volume_scanner_sequence": json.dumps(SEQ),
                "volume_scanner_b_sequence": json.dumps(seq_b),
            },
            "timestamps": {},
        }
    )
    cal = {
        "galvo_amplitude": 0.4,
        "galvo_center": 0.1,
        "piezo_amplitude": 30.0,
        "piezo_center": 3.0,
    }
    got = asyncio.run(client.acquire_volume_two_sided(side_a=cal, side_b=cal, num_slices=3))
    assert got["A"]["sequence"] == SEQ and got["B"]["sequence"] == seq_b


def test_a_device_that_reports_no_sequence_is_a_volume_without_one():
    client = _client({"data": {"volume_scanner": np.zeros((3, 2, 2), np.uint16)}})
    got = asyncio.run(client.acquire_volume(num_slices=3))
    assert got["success"] and "sequence" not in got


def test_the_client_hands_on_when_the_bottom_camera_took_its_frame():
    client = _client(
        {
            "data": {"bottom_camera": np.zeros((4, 4), np.uint16)},
            "timestamps": {"bottom_camera": 1794700000.5},
        }
    )
    client.set_camera_led_mode = AsyncMock()  # type: ignore[method-assign]
    got = asyncio.run(client.capture_bottom_image())
    assert got["acquired_at_epoch"] == 1794700000.5


# ---- the run writes it -----------------------------------------------------


def _orch_with(result):
    ex = ExperimentState()
    ex.add_embryo("embryo_1", position={"x": 0.0, "y": 0.0}, calibration={"galvo_center": 0.0})
    c = MagicMock()
    c.move_to_position = AsyncMock(return_value={"success": True})
    c.acquire_volume = AsyncMock(return_value=result)
    orch = TimelapseOrchestrator(c, ex)
    calls: list[dict] = []

    async def cb(embryo_id, timepoint, data, volume_path=None, **extra):
        calls.append(extra)
        return {"volume_uid": "v"}

    orch.on_volume_callback = cb
    return orch, ex.embryos["embryo_1"], calls


def test_the_run_hands_the_sequence_to_whoever_stores_the_volume_in_utc():
    vol = np.zeros((3, 2, 2), np.uint16)
    orch, embryo, calls = _orch_with({"success": True, "volume": vol, "sequence": SEQ})
    asyncio.run(orch._acquire_embryo(embryo))
    assert calls[0]["hardware"] == ON_DISK


def test_the_volume_sidecar_keeps_what_the_hardware_did(tmp_path):
    from gently.app.agent import MicroscopyAgent

    store = FileStore(tmp_path)
    store.create_session("s1")
    agent = MicroscopyAgent.__new__(MicroscopyAgent)
    agent.experiment = ExperimentState()
    agent.experiment.add_embryo("embryo_1", position={"x": 0.0, "y": 0.0})
    agent.store, agent.viz_server = store, None
    agent.sessions = SimpleNamespace(session_id="s1")
    agent._emit_event = lambda *a, **k: None  # type: ignore[method-assign]
    agent._auto_save_if_due = lambda: None  # type: ignore[method-assign]

    # Six slices: tifffile takes a stack of three or four for colour planes.
    vol = np.zeros((6, 2, 2), np.uint16)
    asyncio.run(agent.on_volume_acquired("embryo_1", 1, vol, hardware=ON_DISK))
    path = store.get_volume_path("s1", "embryo_1", 1)
    meta = yaml.safe_load(Path(str(path).replace(".tif", ".meta.yaml")).read_text())
    assert meta["metadata"]["hardware"] == ON_DISK


# ---- a brightfield frame ---------------------------------------------------


def _bf_rig(room="off"):
    """A microscope that notes, with the time, each thing it is asked to do."""
    log: list[tuple[str, float]] = []
    state = {"room": room}
    c = MagicMock()

    async def capture(use_led=False, exposure_ms=None):
        log.append(("capture", time.time()))
        return {
            "image": np.ones((64, 64), np.uint16),
            "image_path": None,
            "acquired_at_epoch": 1794700000.5,
        }

    async def set_led(s):
        log.append((f"led {s}", time.time()))
        return {"success": True}

    async def room_status():
        return {"success": True, "state": state["room"]}

    async def set_room(s):
        log.append((f"room {s}", time.time()))
        state["room"] = s
        return {"success": True}

    c.capture_bottom_image = AsyncMock(side_effect=capture)
    c.set_led = AsyncMock(side_effect=set_led)
    c.set_led_intensity = AsyncMock(return_value={"success": True})
    c.get_room_light_status = AsyncMock(side_effect=room_status)
    c.set_room_light = AsyncMock(side_effect=set_room)
    c.move_to_position = AsyncMock(return_value={"success": True})
    return c, log


def _one_frame(tmp_path, light, room="off"):
    store = FileStore(tmp_path)
    store.create_session("s1")
    client, log = _bf_rig(room)
    orch = TimelapseOrchestrator(client, ExperimentState(), store=store, session_id="s1")
    orch._bf_light_settle_s = 0.05
    bf = BfOverview(enabled=True, every_seconds=100, light=light, led_intensity_pct=30)
    orch._bf = bf
    asyncio.run(orch._capture_bf_field(bf, 1, 0, 1, None))
    snap = store.list_snapshots("s1")[0]
    # Whole microseconds, which is what the record keeps. On Windows two reads
    # of the clock can share a tick, and the finer of them then looks later.
    return (snap.get("metadata") or {}), {k: int(t * 1e6) / 1e6 for k, t in log}


def test_a_brightfield_frame_keeps_when_its_led_was_on(tmp_path):
    md, at = _one_frame(tmp_path, "led")
    on, off = _epoch(md["light_on_utc"]), _epoch(md["light_off_utc"])
    # On once the LED opened, before the settle and the frame; off once it closed.
    assert at["led Open"] <= on <= at["capture"] <= at["led Closed"] <= off
    assert on + 0.05 <= at["capture"]
    # The camera's own moment for the frame, from the device.
    assert md["exposed_utc"] == "2026-11-14T23:46:40.500000Z"


def test_a_room_light_this_frame_switched_has_a_window_too(tmp_path):
    md, at = _one_frame(tmp_path, "room")
    assert at["room on"] <= _epoch(md["light_on_utc"]) <= at["capture"]
    assert at["room off"] <= _epoch(md["light_off_utc"])


def test_a_room_light_that_did_not_come_on_has_no_window(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("s1")
    client, _ = _bf_rig("off")

    async def refuses(s):
        return {"success": False, "error": "room_light device not configured"}

    client.set_room_light = AsyncMock(side_effect=refuses)
    orch = TimelapseOrchestrator(client, ExperimentState(), store=store, session_id="s1")
    orch._bf_light_settle_s = 0.0
    bf = BfOverview(enabled=True, every_seconds=100, light="room")
    orch._bf = bf
    asyncio.run(orch._capture_bf_field(bf, 1, 0, 1, None))
    md = store.list_snapshots("s1")[0].get("metadata") or {}
    assert md.get("light_on_utc") is None and md.get("light_off_utc") is None


def test_a_light_that_was_already_on_has_no_window_this_frame_can_claim(tmp_path):
    md, _ = _one_frame(tmp_path, "room", room="on")
    assert md.get("light_on_utc") is None and md.get("light_off_utc") is None


def test_a_frame_under_no_light_of_its_own_says_so(tmp_path):
    md, _ = _one_frame(tmp_path, "none")
    assert md.get("light_on_utc") is None


def test_a_one_off_volume_keeps_what_the_hardware_did_and_when_it_began(tmp_path):
    """The agent's own acquire_volume files a volume outside any run: its
    sidecar keeps the same record, and the stack's own time."""
    from gently.app.tools.acquisition_tools import acquire_volume

    store = FileStore(tmp_path)
    store.create_session("s1")
    ex = ExperimentState()
    ex.add_embryo("embryo_1", position={"x": 0.0, "y": 0.0})
    agent = SimpleNamespace(
        experiment=ex, store=store, session_id="s1", viz_server=None, temperature_sampler=None
    )
    client = MagicMock()
    client.move_to_position = AsyncMock(return_value={"success": True})
    client.acquire_volume = AsyncMock(
        return_value={
            "success": True,
            "volume": np.zeros((6, 2, 2), np.uint16),
            "acquired_at_epoch": SEQ["scan_started"],
            "sequence": SEQ,
        }
    )
    asyncio.run(
        acquire_volume(
            embryo_id="embryo_1",
            num_slices=6,
            allow_uncalibrated=True,
            context={"agent": agent, "client": client},
        )
    )
    path = store.get_volume_path("s1", "embryo_1", 0)
    meta = yaml.safe_load(Path(str(path).replace(".tif", ".meta.yaml")).read_text())
    assert meta["metadata"]["hardware"] == ON_DISK
    assert meta["acquired_at_utc"] == "2026-11-14T23:46:40.350000Z"
