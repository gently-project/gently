"""A saved plan runs as the sentence it was saved as.

Templates already existed: the tactic library under agent/tactic_library/,
listed by Operate's "Saved tactic" mode, run through /api/operate/run-tactic
and the tactic executor. What did not exist was a plan rich enough to save —
the executor ran a standing_timelapse's cadence and stop condition and
dropped everything else — and a way to save one from the pane.
"""

from __future__ import annotations

import asyncio
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from gently.app.orchestration.tactic_executor import execute_tactic

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The executor runs the whole plan
# ---------------------------------------------------------------------------


class _Emb:
    def __init__(self, role="test"):
        self.role = role
        self.num_slices = 50
        self.exposure_ms = 10.0


class _Orch:
    def __init__(self):
        self.start_kwargs = None

    async def start(self, **kw):
        self.start_kwargs = kw
        return "started"

    def enable_monitoring_mode(self, name, embryo_ids=None, **kw):
        return f"monitor:{name}"


class _CS:
    def transition_tactic(self, *a, **k):
        return True


def _agent(with_client=True):
    embryos = {"embryo_1": _Emb(), "embryo_2": _Emb(), "embryo_3": _Emb("calibration")}
    client = MagicMock()
    client.set_laser_config = AsyncMock(return_value={"success": True})
    return types.SimpleNamespace(
        experiment=types.SimpleNamespace(embryos=embryos),
        timelapse_orchestrator=_Orch(),
        context_store=_CS(),
        session_id="sess1",
        client=client if with_client else None,
    )


PLAN = {
    "cadence_s": 300,
    "interval": 300,
    "stop_condition": "duration:12h",
    "condition_value": None,
    "monitoring_mode": "idle",
    "num_slices": 80,
    "exposure_ms": 12,
    "laser_config": "488 and 561",
    "dic": {"enabled": True, "every_seconds": 600, "position": None, "exposure_ms": 8},
    "stop_conditions": {"embryo_2": "hatching"},
}


def _run(agent, structure):
    tactic = {
        "id": "t1",
        "kind": "standing_timelapse",
        "state": "planned",
        "scope": {"mode": "embryos", "embryo_ids": ["embryo_1", "embryo_2"]},
        "structure": structure,
    }
    return asyncio.run(execute_tactic(agent, tactic))


def test_a_saved_plan_reaches_the_orchestrator_whole():
    agent = _agent()
    res = _run(agent, PLAN)
    assert res["ok"], res
    kw = agent.timelapse_orchestrator.start_kwargs
    assert kw["embryo_ids"] == ["embryo_1", "embryo_2"]
    assert kw["base_interval_seconds"] == 300
    assert kw["stop_condition"] == "duration:12h"
    assert kw["dic"] == PLAN["dic"], "the DIC channel was dropped on the way"
    assert kw["stop_conditions"] == {"embryo_2": "hatching"}, "the per-embryo endings were dropped"


def test_the_spim_settings_are_applied_to_exactly_the_runs_embryos():
    agent = _agent()
    _run(agent, PLAN)
    e = agent.experiment.embryos
    assert (e["embryo_1"].num_slices, e["embryo_1"].exposure_ms) == (80, 12.0)
    assert (e["embryo_2"].num_slices, e["embryo_2"].exposure_ms) == (80, 12.0)
    assert (e["embryo_3"].num_slices, e["embryo_3"].exposure_ms) == (50, 10.0), (
        "a reference embryo was touched"
    )


def test_the_laser_preset_is_set_on_the_controller_once():
    agent = _agent()
    _run(agent, PLAN)
    agent.client.set_laser_config.assert_awaited_once_with("488 and 561")


def test_a_plan_that_predates_channels_runs_exactly_as_before():
    # The Adaptive start has always seeded {cadence_s, interval, stop_condition,
    # condition_value, monitoring_mode}. Those templates must keep working.
    agent = _agent()
    _run(
        agent,
        {
            "cadence_s": 120,
            "interval": 120,
            "stop_condition": "manual",
            "condition_value": None,
            "monitoring_mode": "idle",
        },
    )
    kw = agent.timelapse_orchestrator.start_kwargs
    assert "dic" not in kw and "stop_conditions" not in kw
    agent.client.set_laser_config.assert_not_awaited()
    assert agent.experiment.embryos["embryo_1"].num_slices == 50


def test_a_refused_laser_preset_stops_the_run_from_starting():
    # Every timepoint would otherwise image with the wrong lasers.
    agent = _agent()
    agent.client.set_laser_config = AsyncMock(side_effect=RuntimeError("no such preset"))
    res = _run(agent, PLAN)
    assert not res["ok"]
    assert "no such preset" in res["message"]
    assert agent.timelapse_orchestrator.start_kwargs is None, "the run started anyway"


# ---------------------------------------------------------------------------
# Saving from the pane
# ---------------------------------------------------------------------------


def _lib_app(context_store):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import gently.ui.web.auth as auth
    from gently.ui.web.routes.tactic_library import create_router

    server = MagicMock()
    server.context_store = context_store
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_the_pane_saves_the_same_document_the_agent_would():
    cs = MagicMock()
    cs.save_tactic = MagicMock(return_value="tac_1234")
    r = _lib_app(cs).post(
        "/api/tactic_library",
        json={
            "name": "overnight two-colour",
            "kind": "standing_timelapse",
            "structure": PLAN,
            "scope": {"mode": "global"},
            "rationale": "Every 5 min: …",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"success": True, "id": "tac_1234", "name": "overnight two-colour"}
    (tactic,), kwargs = cs.save_tactic.call_args
    assert kwargs == {"name": "overnight two-colour"}
    assert tactic["kind"] == "standing_timelapse" and tactic["structure"] == PLAN
    assert tactic["created_by"] == "operate"


@pytest.mark.parametrize(
    "body", [{"structure": PLAN}, {"name": "x"}, {"name": "x", "structure": {}}]
)
def test_a_template_needs_a_name_and_a_plan(body):
    cs = MagicMock()
    r = _lib_app(cs).post("/api/tactic_library", json=body)
    assert r.status_code == 400
    cs.save_tactic.assert_not_called()


def test_saving_without_a_context_store_is_503():
    r = _lib_app(None).post("/api/tactic_library", json={"name": "x", "structure": PLAN})
    assert r.status_code == 503


# ---------------------------------------------------------------------------
# The pane
# ---------------------------------------------------------------------------


def _wire_body() -> str:
    start = OPERATE.index("if (_wired) return;")
    end = OPERATE.index("\n    async function ", start)
    return OPERATE[start:end]


def test_save_this_plan_is_on_the_pane_and_wired():
    assert 'id="op-plan-save"' in HTML
    assert "$('op-plan-save')" in _wire_body() and "savePlan" in _wire_body()
    fn = OPERATE[OPERATE.index("async function savePlan()") :][:1200]
    assert "AcquisitionPlan.toStructure(plan)" in fn
    assert "'/api/tactic_library'" in fn
    assert "kind: 'standing_timelapse'" in fn


def test_the_library_says_each_plan_as_its_sentence():
    fn = OPERATE[OPERATE.index("async function loadLibrary()") :][:1600]
    assert "AcquisitionPlan.fromStructure(t.structure)" in fn
    assert "AcquisitionPlan.describe(" in fn
