"""The session snapshot follows the run, and is written at shutdown.

conversation.json was written only after a conversation turn, so a run
driven from the pane with nobody talking to the agent left it where the
last chat ended — on the rig, at t1 while the run was at t15 — and nothing
saved it when the process went away. Also: the GPU probe read a torch
attribute that does not exist, so the rig never listed its GPU.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from gently.harness.session.manager import SessionManager

ROOT = Path(__file__).resolve().parents[1]
AGENT = (ROOT / "gently" / "app" / "agent.py").read_text(encoding="utf-8")
LAUNCH = (ROOT / "launch_gently.py").read_text(encoding="utf-8")
MESH = (ROOT / "gently" / "mesh" / "capability_provider.py").read_text(encoding="utf-8")


def _manager():
    mgr = SessionManager(store=MagicMock(), storage_path="/tmp/test")
    mgr._session_id = "s1"
    return mgr


def test_a_landing_volume_saves_the_snapshot_at_most_once_a_minute(monkeypatch):
    import time

    mgr = _manager()
    experiment = MagicMock()
    experiment.embryos = {}
    experiment.to_dict.return_value = {"embryos": {}}
    t = {"now": 1000.0}
    monkeypatch.setattr(time, "monotonic", lambda: t["now"])

    assert mgr.auto_save_if_due(experiment, [], "") is True
    assert mgr.store.save_session_snapshot.call_count == 1
    t["now"] += 10
    assert mgr.auto_save_if_due(experiment, [], "") is False, "ten seconds later: throttled"
    assert mgr.store.save_session_snapshot.call_count == 1
    t["now"] += 60
    assert mgr.auto_save_if_due(experiment, [], "") is True
    assert mgr.store.save_session_snapshot.call_count == 2


def test_no_session_no_save():
    mgr = SessionManager(store=MagicMock(), storage_path="/tmp/test")
    experiment = MagicMock()
    experiment.embryos = {}
    experiment.to_dict.return_value = {}
    mgr.auto_save_if_due(experiment, [], "")
    mgr.store.save_session_snapshot.assert_not_called()


def test_the_volume_callback_saves_off_the_loop():
    fn = AGENT[AGENT.index("    async def on_volume_acquired(") :]
    fn = fn[: fn.index('        return {\n            "volume_uid": volume_uid,')]
    assert "await asyncio.to_thread(self._auto_save_if_due)" in fn


def test_shutdown_saves_the_session_before_the_server_stops():
    tail = LAUNCH[LAUNCH.index("    finally:") :][:1400]
    save = tail.index("agent.save_session()")
    stop = tail.index("await agent.viz_server.stop()")
    assert save < stop


def test_the_gpu_probe_reads_the_attribute_torch_has():
    assert "props.total_memory" in MESH and "props.total_mem " not in MESH
    assert "total_mem /" not in MESH
