"""A volume's acquired_at is when its stack began, not when its file was saved.

"what is the time between the acquisition of the two spim views for any
timepoint for any embryo?" The metadata said 0.3 to 0.4 s. The device log
said 2.4 s. A two-sided round takes side A, then side B, and only then saves
both, and acquired_at was the clock at saving.

The device now reports when it set the scan running, the client hands that
on, and the store writes it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import yaml

# Patch the hardware stack the way the side-param test does, by loading it.
_spec = importlib.util.spec_from_file_location(
    "lightsheet_side_param", Path(__file__).with_name("test_lightsheet_side_param.py")
)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))

from gently.core.file_store import FileStore  # noqa: E402
from gently.hardware.dispim.client import DiSPIMMicroscope  # noqa: E402
from gently.hardware.dispim.devices.acquisition import DiSPIMVolumeScanner  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def test_the_device_reads_the_time_the_scan_was_set_running():
    core, scanner = MagicMock(), MagicMock()
    core.isSequenceRunning.return_value = False
    core.getRemainingImageCount.return_value = 0
    core.getBufferTotalCapacity.return_value = 1000
    vs = DiSPIMVolumeScanner(
        scanner=scanner, camera=MagicMock(), piezo=MagicMock(), laser_control=MagicMock(), core=core
    )
    vs.configure(
        num_slices=2,
        exposure_ms=10.0,
        galvo_amplitude=0.5,
        galvo_center=0.0,
        piezo_amplitude=25.0,
        piezo_center=50.0,
    )
    started: list[float] = []
    scanner.set_spim_state.side_effect = lambda s: (
        started.append(vs._scan_started) if s == "Running" else None
    )
    vs.trigger()
    for t in threading.enumerate():
        if t is not threading.current_thread():
            t.join(timeout=5)
    # Stamped before the scan was told to run, and that is what a read gives:
    # not the later moment the lasers were put out.
    assert started and started[0] is not None
    reading = vs.read()[vs.name]
    assert reading["timestamp"] == started[0] <= vs._last_volume_time


def test_the_client_hands_the_stacks_time_on():
    client = DiSPIMMicroscope.__new__(DiSPIMMicroscope)

    async def fake_submit(name, kwargs, timeout):
        event = {
            "data": {"volume_scanner_b": np.zeros((2, 3, 4), dtype=np.uint16)},
            "timestamps": {"volume_scanner_b": 1794700000.25},
        }
        return {"success": True, "documents": {"events": [event]}}

    client._submit_plan_and_wait = fake_submit  # type: ignore[method-assign]
    got = asyncio.run(client.acquire_volume(num_slices=2, side="B"))
    assert got["success"] and got["acquired_at_epoch"] == 1794700000.25


def test_the_store_writes_the_time_it_is_given_and_now_when_given_none(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("s1", name="two sided")
    store.register_embryo("s1", "embryo_1")
    vol = np.zeros((2, 8, 8), dtype=np.uint16)
    a = "2026-11-15T09:14:11.400000"
    b = "2026-11-15T09:14:13.780000"
    store.put_volume("s1", "embryo_1", 0, vol, side="A", acquired_at=a)
    pb = store.put_volume("s1", "embryo_1", 0, vol, side="B", acquired_at=b)
    pa = store.get_volume_path("s1", "embryo_1", 0)

    def at(p):
        meta = yaml.safe_load(Path(str(p).replace(".tif", ".meta.yaml")).read_text())
        return datetime.fromisoformat(str(meta["acquired_at"]))

    assert (at(pb) - at(pa)).total_seconds() == 2.38
    # Whoever gives no time gets the time of saving, as before.
    p = store.put_volume("s1", "embryo_1", 1, vol)
    assert abs((at(p) - datetime.now()).total_seconds()) < 5


def test_the_run_passes_the_time_to_whoever_stores_the_volume():
    timelapse = (REPO / "gently/app/orchestration/timelapse.py").read_text(encoding="utf-8")
    agent = (REPO / "gently/app/agent.py").read_text(encoding="utf-8")
    assert 'extra["acquired_at"] = datetime.fromtimestamp(' in timelapse
    assert agent.count("acquired_at=acquired_at,") == 2  # the moved file, and the written one
