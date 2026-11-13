"""A button raises the SPIM head fully, beside HALT.

"in spim head surface in operate panel, along with the HALT button, we also
need a button to raise the spim head to 25000 - a reset button or something."

The top is the F-drive's own limit, never a number from the request.
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

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
CLIENT = (
    Path(__file__).resolve().parents[1] / "gently" / "hardware" / "dispim" / "client.py"
).read_text(encoding="utf-8")


class _Status:
    def wait(self):
        pass


class _FDrive:
    """A fenced positioner: limits, read, set — what the handler touches."""

    name = "ZStage:V:37"
    limits = (30.0, 25000.0)

    def __init__(self, at=52.0):
        self.pos = at
        self.moves: list[float] = []

    def read(self):
        return {self.name: {"value": self.pos}}

    def set(self, target):
        self.moves.append(target)
        self.pos = float(target)
        return _Status()


def _dl(**devices) -> DeviceLayerServer:
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.devices = dict(devices)
    dl._state_pause_counter = 0
    dl._state_latest = {}
    dl._state_subscribers = []
    return dl


def _run(dl):
    resp = asyncio.run(dl.handle_raise_fdrive(None))
    return resp.status, json.loads(resp.text)


def test_the_head_goes_to_the_drives_own_top():
    fd = _FDrive(at=52.0)
    status, body = _run(_dl(fdrive=fd))
    assert status == 200 and body["success"] is True
    assert fd.moves == [25000.0], "the top is the device's limit, not a request number"
    assert body["position"] == 25000.0 and body["from"] == 52.0
    assert body["distance_to_floor"] == 25000.0 - 30.0


def test_polling_backs_off_for_the_long_move_and_comes_back():
    dl = _dl(fdrive=_FDrive())
    _run(dl)
    assert dl._state_pause_counter == 0 and dl._state_latest["paused"] is False


def test_no_fdrive_is_503():
    status, body = _run(_dl())
    assert status == 503 and "F-drive" in body["error"]


def test_a_move_that_fails_is_reported():
    fd = _FDrive()

    def boom(target):
        raise RuntimeError("controller busy")

    fd.set = boom
    status, body = _run(_dl(fdrive=fd))
    assert status == 500 and "controller busy" in body["error"]


def test_the_device_layer_serves_the_route():
    src = Path(DeviceLayerServer.__module__.replace(".", "/") + ".py")
    src = Path(__file__).resolve().parents[1] / src
    text = src.read_text(encoding="utf-8")
    assert 'add_post("/api/spim/fdrive/raise", self.handle_raise_fdrive)' in text


# ── agent side ───────────────────────────────────────────────────────────


def _app(client):
    server = MagicMock()
    server.agent_bridge.agent.client = client
    server.agent_bridge.agent.lightsheet_monitor = None
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_the_route_asks_the_client_to_raise():
    client = MagicMock()
    client.raise_fdrive = AsyncMock(return_value={"success": True, "position": 25000.0})
    r = _app(client).post("/api/devices/spim/fdrive/raise")
    assert r.status_code == 200 and r.json()["position"] == 25000.0
    client.raise_fdrive.assert_awaited_once_with()


def test_the_route_without_a_microscope_is_503():
    server = MagicMock()
    server.agent_bridge = None
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    assert TestClient(app).post("/api/devices/spim/fdrive/raise").status_code == 503


def test_the_client_posts_to_the_device_layers_raise():
    fn = CLIENT[CLIENT.index("async def raise_fdrive(self)") :][:300]
    assert '_api_post("/api/spim/fdrive/raise", {})' in fn


# ── the pane ─────────────────────────────────────────────────────────────


def test_the_button_is_on_the_head_panel_and_halt_is_on_every_view():
    """Raise head sat beside HALT inside the SPIM head's gauge, "where the
    hand goes when the head must get out of the way". The gauge is the Head
    panel now, on screen with either camera, and Raise head is on it. HALT is
    in the Devices toolbar, once, on every view of the tab: a stop that is
    only on one pane is not there when the hand reaches for it from another."""
    head = HTML[HTML.index('id="op-gauge-fd"') : HTML.index('id="op-stage-panel"')]
    raise_at = head.index('id="op-fd-raise"')
    assert "25000" in head[raise_at - 200 : raise_at + 200]
    bar = HTML[HTML.index('class="devices-header-bar"') : HTML.index('id="devices-view-operate"')]
    assert 'id="op-halt"' in bar, "HALT is not in the toolbar"
    assert HTML.count('id="op-halt"') == 1


def test_the_button_is_wired_in_wire_and_says_it_is_travelling():
    wire = OPERATE[OPERATE.index("if (_wired) return;") :]
    assert "raise.addEventListener('click', raiseHead)" in wire
    fn = OPERATE[OPERATE.index("async function raiseHead()") :][:900]
    assert "postJSON('/api/devices/spim/fdrive/raise', {})" in fn
    assert "b.textContent = 'Raising…'" in fn
    assert "fd.refresh()" in fn
