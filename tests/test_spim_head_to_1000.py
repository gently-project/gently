"""A button brings the SPIM head to 1000 µm, beside Raise head.

"the spim head control panel going from 25000 to 30 — I think there must be
a way to go to 500 easily. Direct from 25000 to 500, or rather 1000.
Something that says cleanly go to 1000."

The device layer fences the height to the F-drive's own limits; the pane's
one number is 1000.
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
    name = "ZStage:V:37"
    limits = (30.0, 25000.0)

    def __init__(self, at=25000.0):
        self.pos = at
        self.moves: list[float] = []

    def read(self):
        return {self.name: {"value": self.pos}}

    def set(self, target):
        self.moves.append(target)
        self.pos = float(target)
        return _Status()


class _Req:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def _dl(**devices) -> DeviceLayerServer:
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.devices = dict(devices)
    dl._state_pause_counter = 0
    dl._state_latest = {}
    dl._state_subscribers = []
    return dl


def _run(dl, body):
    resp = asyncio.run(dl.handle_goto_fdrive(_Req(body)))
    return resp.status, json.loads(resp.text)


def test_the_head_goes_to_the_height_asked():
    fd = _FDrive(at=25000.0)
    status, body = _run(_dl(fdrive=fd), {"position": 1000})
    assert status == 200 and body["success"] is True
    assert fd.moves == [1000.0]
    assert body["position"] == 1000.0 and body["from"] == 25000.0
    assert body["distance_to_floor"] == 1000.0 - 30.0


def test_a_height_outside_the_drives_limits_is_refused_unmoved():
    fd = _FDrive(at=25000.0)
    status, body = _run(_dl(fdrive=fd), {"position": 10})
    assert status == 400 and "outside limits" in body["error"]
    assert fd.moves == []
    assert body["position"] == 25000.0


def test_a_missing_number_is_400():
    status, body = _run(_dl(fdrive=_FDrive()), {})
    assert status == 400


def test_no_fdrive_is_503():
    status, body = _run(_dl(), {"position": 1000})
    assert status == 503 and "F-drive" in body["error"]


def test_the_device_layer_serves_the_route():
    src = Path(DeviceLayerServer.__module__.replace(".", "/") + ".py")
    src = Path(__file__).resolve().parents[1] / src
    text = src.read_text(encoding="utf-8")
    assert 'add_post("/api/spim/fdrive/goto", self.handle_goto_fdrive)' in text


# ── agent side ───────────────────────────────────────────────────────────


def _app(client):
    server = MagicMock()
    server.agent_bridge.agent.client = client
    server.agent_bridge.agent.lightsheet_monitor = None
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_the_route_asks_the_client_for_the_height():
    client = MagicMock()
    client.goto_fdrive = AsyncMock(return_value={"success": True, "position": 1000.0})
    r = _app(client).post("/api/devices/spim/fdrive/goto", json={"position": 1000})
    assert r.status_code == 200 and r.json()["position"] == 1000.0
    client.goto_fdrive.assert_awaited_once_with(1000.0)


def test_the_route_wants_a_number():
    client = MagicMock()
    client.goto_fdrive = AsyncMock()
    assert _app(client).post("/api/devices/spim/fdrive/goto", json={}).status_code == 400
    client.goto_fdrive.assert_not_awaited()


def test_the_client_posts_to_the_device_layers_goto():
    fn = CLIENT[CLIENT.index("async def goto_fdrive(self, position: float)") :][:300]
    assert '_api_post("/api/spim/fdrive/goto", {"position": float(position)})' in fn


# ── the pane ─────────────────────────────────────────────────────────────


def test_the_button_sits_with_raise_head_and_names_its_height():
    at = HTML.index('id="op-fd-to"')
    raise_at = HTML.index('id="op-fd-raise"')
    assert 0 < at - raise_at < 400, "To 1000 µm is not beside Raise head"
    assert 'data-fd-to="1000"' in HTML[at - 100 : at + 200]
    assert "To 1000 µm" in HTML[at : at + 240]


def test_the_button_is_wired_and_says_it_is_travelling():
    wire = OPERATE[OPERATE.index("if (_wired) return;") :]
    assert "headTo(Number(to.dataset.fdTo))" in wire
    fn = OPERATE[OPERATE.index("async function headTo(um)") :][:900]
    assert "postJSON('/api/devices/spim/fdrive/goto', { position: um })" in fn
    assert "b.textContent = 'Going…'" in fn
    assert "fd.refresh()" in fn
