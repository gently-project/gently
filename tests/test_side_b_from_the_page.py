"""Side B can be seen, calibrated and run from the page.

The first run that took a volume from each side (2026-11-14, one embryo, five
timepoints) wrote side B beside side A, and nothing on the page could show
it, calibrate it or ask for it: "from the embryos tab -- how does one view
the a or b side view?" The routes took no side, Calibrate sent none and Start
sent no ``sides``, so the test was driven through the API.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core.file_store import FileStore
from gently.ui.web import auth
from gently.ui.web.routes import sessions as sessions_routes

pytest.importorskip("tifffile")

JS = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
WEB = JS.parents[1]
EMBRYOS = (JS / "embryos.js").read_text(encoding="utf-8")
OPERATE = (JS / "operate.js").read_text(encoding="utf-8")
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1", position_x=0.0, position_y=0.0)
    # The JPEG is stretched to its own range, so the two differ in where
    # they are bright as well as in how bright.
    a = np.zeros((4, 8, 16), np.uint16)
    a[:, :4, :8] = 100
    b = np.zeros((4, 8, 16), np.uint16)
    b[:, 4:, 8:] = 900
    store.put_volume("s1", "embryo_1", 1, a)
    store.put_volume("s1", "embryo_1", 1, b, side="B")
    server = MagicMock()
    server.agent_bridge.agent.store = store
    server.agent_bridge.agent.session_id = "s1"
    app = FastAPI()
    app.include_router(sessions_routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app), store


def test_each_sides_picture_is_its_own(client):
    c, store = client
    base = "/api/sessions/s1/projection?embryo=embryo_1&t=1"
    a, b = c.get(base), c.get(base + "&side=B")
    assert a.status_code == 200 and b.status_code == 200
    assert a.content != b.content
    assert c.get(base + "&side=A").content == a.content  # A is what no side means
    assert "B" in store.get_volume_path("s1", "embryo_1", 1, "B").parts


def test_each_sides_counts_are_its_own(client):
    c, _ = client
    base = "/api/sessions/s1/embryos/embryo_1/volumes/1"
    for what in ("projection.u16", "slice/0.u16"):
        a, b = c.get(f"{base}/{what}"), c.get(f"{base}/{what}?side=B")
        assert a.status_code == 200 and b.status_code == 200, what
        assert np.frombuffer(a.content, np.uint16).max() == 100, what
        assert np.frombuffer(b.content, np.uint16).max() == 900, what


def test_a_side_is_a_folder_name_so_only_a_and_b_are_taken(client):
    c, _ = client
    for bad in ("..", "C", "../../x"):
        r = c.get(f"/api/sessions/s1/projection?embryo=embryo_1&t=1&side={bad}")
        assert r.status_code == 400, bad
        r = c.get(f"/api/sessions/s1/embryos/embryo_1/volumes/1/projection.u16?side={bad}")
        assert r.status_code == 400, bad


def test_a_session_with_no_side_b_says_so(client):
    c, store = client
    store.put_volume("s1", "embryo_1", 2, np.zeros((2, 4, 4), np.uint16))
    assert c.get("/api/sessions/s1/projection?embryo=embryo_1&t=2&side=B").status_code == 404


def test_the_embryos_tab_has_a_switch_only_where_there_is_a_side_b():
    assert 'id="embryos-side"' in INDEX and "EmbryosManager.setSide('B')" in INDEX
    switch = INDEX[INDEX.index('id="embryos-side"') :][:200]
    assert " hidden>" in switch
    assert "host.hidden = !this._sideSeen[this.currentSessionId];" in EMBRYOS
    # Every picture the tab asks for carries the side: tile, scrub, viewer, planes.
    assert EMBRYOS.count("this.sideQ()") == 4 and EMBRYOS.count("?side=${this.side}") == 2


def test_calibrate_and_start_can_ask_for_side_b():
    assert 'id="cal-side"' in INDEX and 'id="op-plan-sides"' in INDEX
    assert "if (_calSide === 'B') body.side = 'B';" in OPERATE
    # Side B is measured by the scan routine only.
    assert "if (side !== 'A' && $('cal-method')) $('cal-method').value = 'scan';" in OPERATE
    assert "sides: v('op-plan-sides')," in OPERATE
