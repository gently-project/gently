"""The XY stage, from the page.

"one more feature i want in the bottom cam view - there is no way to move
the xy stage..."

It was a card on the Bottom cam pane. It is the Stage panel of the workspace
now, on screen with either camera, which is also where the last piece of the
XY lock showed itself: the jog refused whenever the SPIM head was within
1000 µm of its floor, and the rig images at about 85.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.ui.web import auth
from gently.ui.web.routes.data import create_router

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
PAD = (WEB / "static" / "js" / "panels" / "stage-pad.js").read_text(encoding="utf-8")
DATA = (WEB / "routes" / "data.py").read_text(encoding="utf-8")


def _client(*, at=(1000.0, 2000.0), floor=5000.0, envelope=None, move_ok=True):
    client = MagicMock()
    client.get_stage_position = AsyncMock(return_value=at)
    client.get_fdrive = AsyncMock(
        return_value={"distance_to_floor": floor} if floor is not None else {}
    )
    client.get_stage_envelope = AsyncMock(return_value=envelope)
    client.move_to_position = AsyncMock(
        return_value={"success": True} if move_ok else {"success": False, "error": "motor fault"}
    )
    return client


def _app(client):
    server = MagicMock()
    server.agent_bridge.agent.client = client
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


class TestTheJog:
    def test_moves_by_the_step_from_where_the_stage_is(self):
        c = _client()
        r = _app(c).post("/api/devices/stage/jog", json={"dx": 200, "dy": -50})
        assert r.status_code == 200, r.text
        assert r.json() == {
            "success": True,
            "x": 1200.0,
            "y": 1950.0,
            "from": [1000.0, 2000.0],
            "clamped": False,
            "moved": True,
        }
        c.move_to_position.assert_awaited_once_with(1200.0, 1950.0)

    @pytest.mark.parametrize("floor", [85.0, 300.0, 999.0, 5000.0, None])
    def test_the_head_being_down_does_not_refuse_a_jog(self, floor):
        """ "The sample at objective xy locked — that feature — I need to get
        rid of it." It went from the page on 2026-11-08; this route kept its
        own copy (409, "XY is locked") until 2026-11-13."""
        c = _client(floor=floor)
        r = _app(c).post("/api/devices/stage/jog", json={"dx": 200, "dy": 0})
        assert r.status_code == 200, r.text
        c.move_to_position.assert_awaited_once_with(1200.0, 2000.0)
        # The head is not even asked about: nothing here depends on it.
        c.get_fdrive.assert_not_awaited()

    def test_nothing_on_the_route_or_the_pad_is_a_lock(self):
        route = DATA[DATA.index('@router.post("/api/devices/stage/jog"') :]
        route = route[: route.index("\n    @router.")]
        assert "409" not in route and "get_fdrive" not in route
        assert "ENGAGED_WITHIN_UM" not in DATA
        assert "is-locked" not in PAD and "locked()" not in PAD

    def test_stops_at_the_edge_of_an_enforced_envelope(self):
        env = {"x_min": 0.0, "x_max": 1100.0, "y_min": 0.0, "y_max": 9000.0, "enforced": True}
        c = _client(envelope=env)
        r = _app(c).post("/api/devices/stage/jog", json={"dx": 500, "dy": 0})
        assert r.status_code == 200
        assert r.json()["x"] == 1100.0 and r.json()["clamped"] is True and r.json()["moved"] is True
        c.move_to_position.assert_awaited_once_with(1100.0, 2000.0)

    def test_already_at_the_edge_does_not_move(self):
        env = {"x_min": 0.0, "x_max": 1000.0, "y_min": 0.0, "y_max": 9000.0, "enforced": True}
        c = _client(envelope=env)
        r = _app(c).post("/api/devices/stage/jog", json={"dx": 500, "dy": 0})
        assert r.status_code == 200 and r.json()["moved"] is False and r.json()["clamped"] is True
        c.move_to_position.assert_not_awaited()

    def test_an_envelope_that_is_not_enforced_does_not_clamp(self):
        env = {"x_min": 0.0, "x_max": 1100.0, "y_min": 0.0, "y_max": 9000.0, "enforced": False}
        c = _client(envelope=env)
        r = _app(c).post("/api/devices/stage/jog", json={"dx": 500, "dy": 0})
        assert r.json()["x"] == 1500.0 and r.json()["clamped"] is False

    def test_bad_input_and_a_failed_motor_are_said(self):
        c = _client(move_ok=False)
        app = _app(c)
        assert app.post("/api/devices/stage/jog", json={"dx": "far", "dy": 0}).status_code == 400
        assert app.post("/api/devices/stage/jog", json={"dx": 0, "dy": 0}).status_code == 400
        assert app.post("/api/devices/stage/jog", json={"dx": 50000, "dy": 0}).status_code == 400
        r = app.post("/api/devices/stage/jog", json={"dx": 10, "dy": 0})
        assert r.status_code == 502 and "motor fault" in r.json()["detail"]

    def test_no_microscope_is_503(self):
        server = MagicMock()
        server.agent_bridge.agent.client = None
        app = FastAPI()
        app.include_router(create_router(server))
        app.dependency_overrides[auth.require_control] = lambda: True
        assert (
            TestClient(app).post("/api/devices/stage/jog", json={"dx": 10, "dy": 0}).status_code
            == 503
        )


class TestThePad:
    def test_the_stage_panel_has_a_pad_named_by_axis(self):
        assert 'id="op-stage-host"' in INDEX and "panels/stage-pad.js" in INDEX
        scope = INDEX[INDEX.index('id="op-pane-scope"') : INDEX.index('id="op-pane-cal"')]
        panel = scope[scope.index('id="op-stage-panel"') :]
        assert 'id="op-stage-host"' in panel, "the pad is not in the Stage panel"
        assert "StagePad.mount('op-stage-host')" in OPERATE
        for needle in (
            "▲ +Y",
            "▼ −Y",
            "◀ −X",
            "+X ▶",
            "/api/devices/stage/jog",
            "ArrowUp",
            "shiftKey",
        ):
            assert needle in PAD, needle
        # The pad never claims a screen direction it cannot know.
        assert "Named by stage axis" in PAD

    def test_a_press_keeps_the_keyboard_on_the_pad(self):
        """Each press redraws the pad. Redrawn, it used to drop the focus, so
        the arrow keys moved the stage once and then scrolled the page."""
        fn = PAD[PAD.index("    function render() {") :]
        fn = fn[: fn.index("\n    }")]
        assert "const hadFocus = host.contains(document.activeElement);" in fn
        assert "if (hadFocus)" in fn and "pad.focus({ preventScroll: true })" in fn
