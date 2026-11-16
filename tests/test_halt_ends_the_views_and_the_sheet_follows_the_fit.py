"""HALT ends the live views, and a fitted side's piezo follows its galvo."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.ui.web import auth
from gently.ui.web.routes.data import create_router

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"


def _app(bottom_running: bool, spim_running: bool) -> tuple[TestClient, MagicMock, MagicMock]:
    client = MagicMock()
    client.halt_motion = AsyncMock(
        return_value={"success": True, "halted": ["xy_stage"], "dark": ["lasers"], "errors": {}}
    )
    bottom, spim = MagicMock(), MagicMock()
    bottom.running, spim.running = bottom_running, spim_running
    bottom.stop, spim.stop = AsyncMock(), AsyncMock()
    server = MagicMock()
    server.agent_bridge.agent.client = client
    server.agent_bridge.agent.bottom_camera_monitor = bottom
    server.agent_bridge.agent.lightsheet_monitor = spim
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app), bottom, spim


def test_halt_stops_the_views_that_are_running() -> None:
    web, bottom, spim = _app(True, True)
    r = web.post("/api/devices/motion/halt")
    assert r.status_code == 200
    assert r.json()["views_stopped"] == ["bottom camera", "light-sheet view"]
    bottom.stop.assert_awaited_once()
    spim.stop.assert_awaited_once()


def test_halt_leaves_a_view_that_is_off_alone() -> None:
    web, bottom, spim = _app(False, True)
    r = web.post("/api/devices/motion/halt")
    assert r.json()["views_stopped"] == ["light-sheet view"]
    bottom.stop.assert_not_awaited()


def test_a_view_that_will_not_stop_does_not_fail_the_halt() -> None:
    web, bottom, _ = _app(True, False)
    bottom.stop.side_effect = RuntimeError("stream stuck")
    r = web.post("/api/devices/motion/halt")
    assert r.status_code == 200
    assert r.json()["halted"] == ["xy_stage"]
    assert r.json()["views_stopped"] == []


def test_the_page_shows_the_views_as_stopped() -> None:
    js = (WEB / "static/js/operate.js").read_text(encoding="utf-8")
    assert "document.addEventListener('gently:halted', viewsHalted)" in js
    menu = (WEB / "static/js/rig-menu.js").read_text(encoding="utf-8")
    assert "new CustomEvent('gently:halted')" in menu


def test_a_fitted_side_has_a_row_tying_piezo_to_galvo() -> None:
    html = (WEB / "templates/index.html").read_text(encoding="utf-8")
    js = (WEB / "static/js/operate.js").read_text(encoding="utf-8")
    for k in ("a", "b"):
        # Hidden until the selected embryo has a fit on that side.
        assert f'id="op-lock-{k}-wrap" hidden' in html
        assert f'id="op-lock-{k}"' in html and f'id="op-lock-{k}-reset"' in html
    assert "wrap.hidden = !f;" in js
    # The piezo goes along the fit's line with the galvo, inside its limits,
    # and a piezo moved by hand is kept as a trim on that line.
    assert "line(v) + _lock[side].trim" in js
    assert "_lock[side].trim = v - line(_pose[side].galvo);" in js
