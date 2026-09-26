"""A run restored from its checkpoint can be carried on.

"there is no way to resume a timelapse."

After a restart the checkpoint put every embryo back where it was, and the
run view drew them as "running · next now" with a Stop each — over a loop
that no longer existed. Now the orchestrator can continue a restored run:
every embryo still going is due now, numbering carries on from the
checkpoint, and the Resume route reaches it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.app.orchestration.timelapse import TimelapseOrchestrator, TimelapseStatus
from gently.core.file_store import FileStore
from gently.harness.state import ExperimentState
from gently.ui.web import auth
from gently.ui.web.routes.data import create_router

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")

POSITIONS = {"embryo_1": {"x": -800.0, "y": -600.0}, "embryo_2": {"x": -200.0, "y": -600.0}}


def _client():
    c = MagicMock()
    c.move_to_position = AsyncMock(return_value={"success": True})
    c.acquire_volume = AsyncMock(return_value={"success": True, "volume": None})
    return c


def _experiment():
    ex = ExperimentState()
    for eid, pos in POSITIONS.items():
        ex.add_embryo(eid, position=dict(pos), calibration={"galvo_center": 0.0})
    return ex


def _orchestrator(store):
    return TimelapseOrchestrator(_client(), _experiment(), store=store, session_id="s1")


@pytest.fixture
def store(tmp_path):
    fs = FileStore(root=tmp_path)
    fs.create_session("s1")
    return fs


def _counts(orch):
    return {eid: e.timepoints_acquired for eid, e in orch.experiment.embryos.items()}


async def _first_life(store):
    """A run that imaged a few rounds, then the process went away."""
    orch = _orchestrator(store)
    msg = await orch.start(base_interval_seconds=0.1, stop_condition="manual")
    assert msg.startswith("Started"), msg
    await asyncio.sleep(0.6)
    counts = _counts(orch)
    assert all(n >= 2 for n in counts.values()), counts
    # Not stop(): stop() is a decision. The process died with the checkpoint
    # on disk, which is what save_state wrote after every acquisition.
    orch._stop_requested = True
    orch._acquisition_task.cancel()
    try:
        await orch._acquisition_task
    except (asyncio.CancelledError, Exception):
        pass
    return counts


def test_a_restored_run_continues_where_it_left_off(store):
    async def scenario():
        before = await _first_life(store)
        # The next process: a fresh orchestrator, embryos from disk, checkpoint applied.
        orch = _orchestrator(store)
        assert not orch.can_continue(), "nothing restored yet"
        assert orch.load_state().startswith("Restored")
        assert orch.get_status().status == TimelapseStatus.IDLE
        assert _counts(orch) == before, "the checkpoint carries the counts"
        assert orch.can_continue()

        msg = await orch.continue_run()
        assert msg.startswith("Continued timelapse: 2 embryo(s) from t"), msg
        assert orch.get_status().status == TimelapseStatus.RUNNING
        await asyncio.sleep(0.5)
        after = _counts(orch)
        await orch.stop("test done")
        return before, after

    before, after = asyncio.run(scenario())
    for eid in POSITIONS:
        assert after[eid] > before[eid], f"{eid} did not carry on from t{before[eid]}"
    # numbering carried on: the first new volume was before+1, never t1 again
    assert min(after.values()) > 1


def test_continue_needs_a_restored_run(store):
    async def scenario():
        orch = _orchestrator(store)
        return await orch.continue_run()

    assert asyncio.run(scenario()).startswith("Nothing to continue")


def test_continue_is_a_resume_when_paused(store):
    async def scenario():
        orch = _orchestrator(store)
        await orch.start(base_interval_seconds=10, stop_condition="manual")
        await orch.pause()
        assert not orch.can_continue(), "paused is not idle"
        msg = await orch.continue_run()
        status = orch.get_status().status
        await orch.stop("test done")
        return msg, status

    msg, status = asyncio.run(scenario())
    assert msg == "Timelapse resumed." and status == TimelapseStatus.RUNNING


def test_a_completed_embryo_is_not_continued(store):
    async def scenario():
        orch = _orchestrator(store)
        await orch.start(base_interval_seconds=10, stop_condition="manual")
        await orch.stop("test done")
        for e in orch.experiment.embryos.values():
            e.is_complete = True
        return orch.can_continue()

    assert asyncio.run(scenario()) is False


# ── the routes ───────────────────────────────────────────────────────────


def _app(orch):
    server = MagicMock()
    agent = server.agent_bridge.agent
    agent.session_id = "s1"
    agent.timelapse_orchestrator = orch
    agent.context_store.get_operation_plan = MagicMock(
        return_value={
            "tactics": [
                {"id": "op_1", "kind": "standing_timelapse", "state": "done"},
                {"id": "op_2", "kind": "reactive_monitor", "state": "done"},
            ]
        }
    )
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app), agent


def _fake_orch(can_continue):
    orch = MagicMock()
    orch.can_continue = MagicMock(return_value=can_continue)
    orch.continue_run = AsyncMock(return_value="Continued timelapse: 2 embryo(s) from t15.")
    orch.resume = AsyncMock(return_value="Timelapse resumed.")
    state = MagicMock()
    state.to_dict = MagicMock(return_value={"status": "idle"})
    state.embryos = {}
    orch.get_status = MagicMock(return_value=state)
    return orch


def test_the_status_says_when_a_run_can_be_carried_on():
    client, _ = _app(_fake_orch(True))
    assert client.get("/api/devices/timelapse/status").json()["resumable"] is True
    client, _ = _app(_fake_orch(False))
    assert client.get("/api/devices/timelapse/status").json()["resumable"] is False


def test_resume_carries_a_restored_run_on_and_wakes_its_tactic():
    orch = _fake_orch(True)
    client, agent = _app(orch)
    r = client.post("/api/devices/timelapse/resume")
    assert r.status_code == 200, r.text
    assert r.json()["continued"] is True
    orch.continue_run.assert_awaited_once()
    orch.resume.assert_not_awaited()
    agent.context_store.transition_tactic.assert_called_once_with("s1", "op_1", "active")
    assert orch._operate_tactic_ids == ["op_1"], "a later stop must mark it done again"


def test_resume_still_resumes_a_paused_run():
    orch = _fake_orch(False)
    client, _ = _app(orch)
    r = client.post("/api/devices/timelapse/resume")
    assert r.status_code == 200
    assert "continued" not in r.json()
    orch.resume.assert_awaited_once()
    orch.continue_run.assert_not_awaited()


# ── the run view ─────────────────────────────────────────────────────────


def test_a_restored_run_gets_a_resume_button_and_no_stop():
    fn = OPERATE[OPERATE.index("async function renderRun()") :][:2600]
    assert "const resumable = !!(st && st.resumable) && !running;" in fn
    assert "actions.hidden = !running && live.length === 0 && !resumable;" in fn
    assert "(resumable ? 'Resume run' : 'Resume')" in fn
    assert "stopb.hidden = !running && live.length === 0;" in fn
    assert "interrupted" in fn


def test_rows_of_a_run_that_is_not_running_say_waiting_and_offer_no_stop():
    fn = OPERATE[OPERATE.index("function runRow(id, r, live)") :][:1900]
    assert ": !live ? 'waiting'" in fn
    assert "r.is_complete || !live ? '' : `next ${fmtWhen(due)}`" in fn
    assert "(r.is_complete || !live ? '<span></span><span></span>' :" in fn
    assert "runRow(id, rows[id], running)" in OPERATE
    assert ".op-runrow.is-waiting" in CSS
