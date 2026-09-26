"""A resumed session comes back on what it was running.

"when resume a session, the what to run ui/ux is in default view - not the
ones i had selected for that session that i have resumed."

The plan kept with the session now records the pane's set ("all" or the
selected embryos) and its mode (adaptive, or which saved tactic), and the
pane puts both back on entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.app.orchestration import tactic_executor
from gently.core.file_store import FileStore
from gently.ui.web import auth
from gently.ui.web.routes.data import create_router

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
DATA = (WEB / "routes" / "data.py").read_text(encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    fs = FileStore(root=tmp_path)
    fs.create_session("s1")
    return fs


def _app(store):
    server = MagicMock()
    agent = server.agent_bridge.agent
    agent.session_id = "s1"
    agent.store = store
    orch = MagicMock()
    orch.start = AsyncMock(return_value="Timelapse started.")
    orch.enable_monitoring_mode = MagicMock(return_value="ok")
    agent.timelapse_orchestrator = orch
    agent.client.set_laser_config = AsyncMock(return_value={"success": True})
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_a_start_from_the_pane_keeps_its_set_and_mode(store):
    r = _app(store).post(
        "/api/devices/timelapse/start",
        json={"interval_seconds": 300, "embryo_ids": ["embryo_2", "embryo_3"], "scope": "selected"},
    )
    assert r.status_code == 200, r.text
    kept = store.get_acquisition_plan("s1")
    assert kept["mode"] == "adaptive"
    assert kept["scope"] == "selected" and kept["embryo_ids"] == ["embryo_2", "embryo_3"]


def test_a_start_without_a_scope_is_all(store):
    _app(store).post("/api/devices/timelapse/start", json={"interval_seconds": 300})
    assert store.get_acquisition_plan("s1")["scope"] == "all"


def test_a_library_run_keeps_which_tactic_it_was(store):
    agent = MagicMock()
    agent.session_id = "s1"
    agent.store = store
    tactic = {"id": "op_9", "name": "Overnight", "kind": "standing_timelapse", "library_id": "tl_3"}
    tactic_executor._keep_plan(agent, {"cadence_s": 300}, ["embryo_1"], "Started timelapse", tactic)
    kept = store.get_acquisition_plan("s1")
    assert kept["mode"] == "library" and kept["library_id"] == "tl_3"
    assert kept["tactic_id"] == "op_9" and kept["name"] == "Overnight"
    assert kept["scope"] == "selected"


def test_a_tactic_not_from_the_library_is_not_called_one(store):
    agent = MagicMock()
    agent.session_id = "s1"
    agent.store = store
    tactic_executor._keep_plan(
        agent, {"cadence_s": 300}, ["embryo_1"], "Started", {"id": "op_1", "name": "Agent's"}
    )
    kept = store.get_acquisition_plan("s1")
    assert kept["mode"] == "tactic" and kept["library_id"] is None


def test_the_run_tactic_route_stamps_the_library_id_and_the_scope():
    route = DATA[DATA.index('@router.post("/api/operate/run-tactic"') :][:3600]
    assert 'tactic["library_id"] = lib_id' in route
    assert 'kept["scope"] = payload["scope"]' in route
    assert 'kept.get("tactic_id") == stored.get("id")' in route, "only the plan this run kept"


# ── the pane ─────────────────────────────────────────────────────────────


def test_the_pane_sends_its_set_with_both_kinds_of_start():
    fn = OPERATE[OPERATE.index("async function startRun()") :][:3600]
    assert "payload.scope = _targetScope;" in fn
    assert "embryo_ids: subjectIds(), scope: _targetScope }" in fn


def test_the_pane_restores_the_set_and_the_mode_from_the_plan():
    fn = OPERATE[OPERATE.index("function restoreWhatToRun(plan)") :][:1400]
    assert "if (plan.scope === 'selected' && ids.length)" in fn
    assert "_targets = ids.slice();" in fn and "setTargetScope('selected');" in fn
    assert "SharedState.set('selectedEmbryoIds', _targets.slice());" in fn
    assert "setTargetScope('all');" in fn
    assert "_selectedLib = plan.library_id;" in fn and "setMode('library');" in fn
    assert "setMode('adaptive');" in fn
    restore = OPERATE[OPERATE.index("async function restorePlan()") :][:1400]
    assert "restoreWhatToRun(d.plan);" in restore


def test_unknown_embryos_in_the_plan_are_dropped():
    fn = OPERATE[OPERATE.index("function restoreWhatToRun(plan)") :][:600]
    assert "filter(id => known.has(id))" in fn
