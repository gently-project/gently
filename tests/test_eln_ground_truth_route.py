"""Tests for the ELN ground-truth authoring route (annotation flywheel write path)."""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client(store):
    from gently.ui.web.auth import require_control
    from gently.ui.web.routes.data import create_router

    app = FastAPI()
    server = MagicMock()
    agent = MagicMock()
    agent.experiment = MagicMock()  # hasattr(agent, "experiment") → True
    agent.store = store
    agent.session_id = "s1"
    server.agent_bridge.agent = agent
    app.include_router(create_router(server))
    app.dependency_overrides[require_control] = lambda: None
    return TestClient(app)


def test_ground_truth_route_persists_range():
    store = MagicMock()
    client = _build_client(store)
    resp = client.post(
        "/api/embryos/embryo_1/ground_truth",
        json={"stage": "comma", "start_timepoint": 40, "end_timepoint": 58, "annotator": "kesh"},
    )
    assert resp.status_code == 200
    store.set_ground_truth.assert_called_once_with("s1", "embryo_1", "comma", 40, 58, "kesh", None)
    assert resp.json()["stage"] == "comma"


def test_ground_truth_route_open_ended_end():
    store = MagicMock()
    client = _build_client(store)
    resp = client.post(
        "/api/embryos/e1/ground_truth",
        json={"stage": "pretzel", "start_timepoint": 90},
    )
    assert resp.status_code == 200
    args = store.set_ground_truth.call_args[0]
    assert args[3] == 90 and args[4] is None  # end_timepoint None = open-ended


def test_ground_truth_route_requires_stage():
    store = MagicMock()
    client = _build_client(store)
    resp = client.post("/api/embryos/e1/ground_truth", json={"start_timepoint": 1})
    assert resp.status_code == 400


def test_ground_truth_route_requires_int_start():
    store = MagicMock()
    client = _build_client(store)
    resp = client.post(
        "/api/embryos/e1/ground_truth", json={"stage": "bean", "start_timepoint": "x"}
    )
    assert resp.status_code == 400


def test_ground_truth_route_benchmark_no_agent_uses_server_store():
    """No agent (launch_viz_server mode) → falls back to server.gently_store."""
    from gently.ui.web.auth import require_control
    from gently.ui.web.routes.data import create_router

    store = MagicMock()
    server = MagicMock()
    server.agent_bridge = None  # benchmark mode: no agent bridge
    server.gently_store = store
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[require_control] = lambda: None
    client = TestClient(app)
    resp = client.post(
        "/api/embryos/e1/ground_truth",
        json={"stage": "comma", "start_timepoint": 5, "session_id": "demo"},
    )
    assert resp.status_code == 200
    store.set_ground_truth.assert_called_once_with("demo", "e1", "comma", 5, None, None, None)
