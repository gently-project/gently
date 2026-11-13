"""The device layer polls positions, and reads properties when asked.

Every Tiger device shares one serial port, so whatever an operator presses
waits behind the read in flight. On 2026-11-08, with XY polled at 5 Hz, the
other axes at 1 Hz and every property swept each 15 s, the pollers' own reads
were logging slow and the sweep held the port 1.5-2.8 s at a time: "there
seems to be some lag between button press and the actual actuation".

"I think we do not need the property sweep at all. We can do the XY 2 Hz one."

So: XY at 2 Hz; the F-drive and the bottom Z at 0.5 Hz; the piezo and the galvo
when something has moved them; the properties once at start and then on
request, and never on a poll tick — a tick that carried them cost every
browser 24 KB and a redraw of the Details table, six times a second.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import gently.ui.web.auth as auth
from gently.ui.web.routes.data import create_router

pytest.importorskip("aiohttp")

from gently.hardware.dispim.device_layer import DeviceLayerServer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DEVICE_LAYER = (ROOT / "gently" / "hardware" / "dispim" / "device_layer.py").read_text(
    encoding="utf-8"
)
DEVICES_JS = (ROOT / "gently" / "ui" / "web" / "static" / "js" / "devices.js").read_text(
    encoding="utf-8"
)
INDEX = (ROOT / "gently" / "ui" / "web" / "templates" / "index.html").read_text(encoding="utf-8")

PROPS = {"Scanner:AB:33": {"BeamEnabled": "No"}, "XYStage:XY:31": {"LowerLimX(mm)": "-500"}}


def _dl() -> DeviceLayerServer:
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.devices = {}
    dl._state_pause_counter = 0
    dl._state_updating_now = False
    dl._state_latest = {"positions": {}, "properties": dict(PROPS), "t": 0.0, "paused": False}
    dl._state_subscribers = [asyncio.Queue(maxsize=32)]
    dl._state_pos_interval_sec = 0.01
    dl._state_slow_pos_interval_sec = 0.01
    dl._state_optics_interval_sec = 3600.0
    dl._state_optics_moved = True
    dl._ls_params = {"galvo": 0.0, "piezo": 0.0, "exposure": 20.0, "side": "A", "mode": "snap"}
    return dl


async def _first(dl: DeviceLayerServer, poller, n: int = 1) -> list[dict]:
    """Run a poller until it has broadcast ``n`` payloads; return them."""
    task = asyncio.create_task(poller())
    try:
        return [
            await asyncio.wait_for(dl._state_subscribers[0].get(), timeout=2.0) for _ in range(n)
        ]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# ── the cadences ─────────────────────────────────────────────────────────


def test_xy_is_asked_for_twice_a_second_and_the_rest_less():
    assert "self._state_pos_interval_sec = 0.5" in DEVICE_LAYER
    assert "self._state_slow_pos_interval_sec = 2.0" in DEVICE_LAYER
    assert "self._state_optics_interval_sec = 10.0" in DEVICE_LAYER


def test_nothing_sweeps_the_properties_on_a_timer():
    assert "_property_poller" not in DEVICE_LAYER
    assert "_state_prop_interval_sec" not in DEVICE_LAYER
    assert not hasattr(DeviceLayerServer, "_property_poller")
    # Read once at start, by the task that used to be the sweep's loop.
    assert "self._state_prop_task = asyncio.create_task(self._sweep_properties())" in DEVICE_LAYER


# ── what a tick carries ──────────────────────────────────────────────────


def test_a_tick_carries_the_snapshot_without_its_properties():
    dl = _dl()
    dl._state_latest["positions"] = {"XYStage:XY:31": {"X": 1.0, "Y": 2.0, "kind": "xy_stage"}}
    tick = dl._tick_payload(heartbeat=True)
    assert "properties" not in tick
    assert tick["positions"]["XYStage:XY:31"]["X"] == 1.0 and tick["heartbeat"] is True
    assert dl._state_latest["properties"] == PROPS, "the snapshot itself keeps them"


@pytest.mark.asyncio
async def test_the_xy_poller_broadcasts_positions_only():
    dl = _dl()
    dl._read_xy_position = lambda: {"XYStage:XY:31": {"X": 5.0, "Y": 6.0, "kind": "xy_stage"}}
    (payload,) = await _first(dl, dl._position_poller)
    assert "properties" not in payload
    assert payload["positions"]["XYStage:XY:31"]["Y"] == 6.0
    assert len(json.dumps(payload)) < 400, "a tick is small enough to send twice a second"


@pytest.mark.asyncio
async def test_a_paused_heartbeat_is_small_too():
    dl = _dl()
    dl._state_pause_counter = 1
    (payload,) = await _first(dl, dl._position_poller)
    assert payload["heartbeat"] is True and payload["paused"] is True
    assert "properties" not in payload


# ── the slow axes ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_piezo_and_galvo_are_read_when_something_moved_them():
    dl = _dl()
    asked: list[bool] = []

    def read(optics=True):
        asked.append(bool(optics))
        return {"ZStage:V:37": {"Position": 114.5, "kind": "fdrive"}}

    dl._read_slow_positions = read
    await _first(dl, dl._slow_positions_poller, n=3)
    assert asked[0] is True, "the first tick reads everything"
    assert asked[1:3] == [False, False], "after that, only the axes a knob can move"

    dl._state_optics_moved = True
    asked.clear()
    await _first(dl, dl._slow_positions_poller, n=2)
    assert asked[0] is True and asked[1] is False


def test_the_slow_read_skips_the_optics_when_not_asked():
    dl = _dl()

    class _Dev:
        def __init__(self, name, value):
            self.name, self._value, self.reads = name, value, 0

        def read(self):
            self.reads += 1
            return {self.name: {"value": self._value}}

    piezo, scanner = _Dev("PiezoStage:P:34", 3.0), _Dev("Scanner:AB:33", (0.1, 0.2))
    fdrive, z = _Dev("ZStage:V:37", 114.5), _Dev("ZStage:Z:32", 25.6)
    dl.devices = {"piezo": piezo, "scanner": scanner, "fdrive": fdrive, "z_stage": z}

    out = dl._read_slow_positions(optics=False)
    assert set(out) == {"ZStage:V:37", "ZStage:Z:32"}
    assert (piezo.reads, scanner.reads, fdrive.reads, z.reads) == (0, 0, 1, 1)

    out = dl._read_slow_positions()
    assert set(out) == {"PiezoStage:P:34", "Scanner:AB:33", "ZStage:V:37", "ZStage:Z:32"}


@pytest.mark.asyncio
async def test_a_new_pose_and_the_end_of_a_pause_mark_the_optics_moved():
    dl = _dl()
    dl._state_optics_moved = False
    req = AsyncMock()
    req.json = AsyncMock(return_value={"exposure": 30.0})
    await dl.handle_lightsheet_params(req)
    assert dl._state_optics_moved is False, "an exposure moves nothing"

    req.json = AsyncMock(return_value={"galvo": 0.5})
    await dl.handle_lightsheet_params(req)
    assert dl._state_optics_moved is True

    dl._state_optics_moved = False
    async with dl.pause_state_updates():
        assert dl._state_optics_moved is False
    assert dl._state_optics_moved is True, "whatever held MMCore may have moved them"


# ── the properties, when asked ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_sweep_reads_once_and_tells_everyone():
    dl = _dl()
    dl._state_latest["properties"] = {}
    reads = []
    dl._read_full_state = lambda: reads.append(1) or dict(PROPS)

    assert await dl._sweep_properties() is True
    assert len(reads) == 1
    assert dl._state_latest["properties"] == PROPS
    sent = dl._state_subscribers[0].get_nowait()
    assert sent["properties"] == PROPS, "the one broadcast that carries them"


@pytest.mark.asyncio
async def test_a_sweep_stands_aside_for_a_plan_and_for_another_sweep():
    dl = _dl()
    dl._read_full_state = lambda: pytest.fail("read while it should not")
    dl._state_pause_counter = 1
    assert await dl._sweep_properties() is False
    dl._state_pause_counter = 0
    dl._state_updating_now = True
    assert await dl._sweep_properties() is False
    assert dl._state_subscribers[0].empty()


@pytest.mark.asyncio
async def test_the_state_route_reads_only_when_asked_to():
    dl = _dl()
    reads = []
    dl._read_full_state = lambda: reads.append("props") or {"Dev": {"P": "fresh"}}
    dl._read_xy_position = lambda: reads.append("xy") or {}
    dl._read_slow_positions = lambda optics=True: reads.append("slow") or {}

    req = MagicMock()
    req.query = {}
    body = json.loads((await dl.handle_devices_state(req)).text)
    assert reads == [] and body["properties"] == PROPS

    req.query = {"refresh": "1"}
    body = json.loads((await dl.handle_devices_state(req)).text)
    assert reads == ["xy", "slow", "props"]
    assert body["properties"] == {"Dev": {"P": "fresh"}}
    assert dl._state_subscribers[0].get_nowait()["properties"] == {"Dev": {"P": "fresh"}}


# ── the agent, and the page ──────────────────────────────────────────────


def _app(client):
    server = MagicMock()
    server.agent_bridge.agent.client = client
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_the_agent_hands_the_snapshot_through_and_the_refresh_with_it():
    client = MagicMock()
    client.is_connected = True
    client.get_device_state = AsyncMock(return_value={"positions": {}, "properties": PROPS})
    app = _app(client)
    assert app.get("/api/devices/state").json()["properties"] == PROPS
    client.get_device_state.assert_awaited_with(refresh=False)
    app.get("/api/devices/state?refresh=1")
    client.get_device_state.assert_awaited_with(refresh=True)


def test_the_agent_says_so_when_there_is_no_microscope():
    assert _app(None).get("/api/devices/state").status_code == 503


def test_the_details_table_reads_while_it_is_on_screen():
    assert "watchProperties(viewName === 'details');" in DEVICES_JS, (
        "opening Details no longer reads the properties"
    )
    assert "readProperties(false);" in DEVICES_JS, "nothing seeds the table or the 3D view's box"
    fn = DEVICES_JS[DEVICES_JS.index("async function readProperties(fresh)") :][:900]
    assert "/api/devices/state${fresh ? '?refresh=1' : ''}" in fn
    assert "ClientEventBus.emit('DEVICE_STATE_UPDATE', d)" in fn, (
        "the 3D view takes the stage's box from the same properties"
    )
    assert 'id="devices-props-read"' in INDEX and 'id="devices-props-age"' in INDEX


def test_a_tick_without_properties_does_not_redraw_the_table():
    body = DEVICES_JS[DEVICES_JS.index("function handlePayload(payload)") :][:1600]
    assert "if (payload.properties && Object.keys(payload.properties).length)" in body
