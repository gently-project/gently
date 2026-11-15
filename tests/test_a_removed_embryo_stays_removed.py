"""An embryo taken off the list is not back after a restart.

"embryo 1 was removed so how come it is back in the embryos list?" It was
removed at 23:20 (its folder moved to removed/, whole). The app was restarted
at 23:28 and the session resumed from its snapshot, which is saved now and
then and still named embryo 1. So embryo 1 was in the list again, and the
next save of the list gave it a new, empty folder beside the one kept under
removed/: listed, and offered for Restore, at once.
"""

from __future__ import annotations

from gently.core.file_store import FileStore
from gently.harness.session.manager import SessionManager
from gently.harness.state import ExperimentState


def _session(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("s1", name="night")
    for eid in ("embryo_1", "embryo_2"):
        store.register_embryo("s1", eid, position_coarse={"x": 1.0, "y": 2.0})
    embryos = {
        eid: {"stage_position": {"x": 1.0, "y": 2.0}, "calibration": {}}
        for eid in ("embryo_1", "embryo_2", "embryo_9")
    }
    store.save_session_snapshot(
        "s1", {"conversation_history": [], "experiment_data": {"embryos": embryos}}
    )
    return store, SessionManager(store=store, storage_path=tmp_path)


def test_a_removed_embryo_is_not_resumed_from_an_older_snapshot(tmp_path):
    store, sessions = _session(tmp_path)
    store.set_aside_embryo("s1", "embryo_1", {"by": "kesavan"})
    experiment = ExperimentState()
    sessions._resume_session("s1", experiment)
    # embryo_9 was never saved to a folder and never removed: it is resumed.
    assert sorted(experiment.embryos) == ["embryo_2", "embryo_9"]


def test_one_put_back_is_resumed_and_so_is_a_new_one_with_the_same_number(tmp_path):
    store, sessions = _session(tmp_path)
    store.set_aside_embryo("s1", "embryo_1", {"by": "kesavan"})
    store.restore_embryo("s1", "embryo_1")
    experiment = ExperimentState()
    sessions._resume_session("s1", experiment)
    assert "embryo_1" in experiment.embryos

    store.set_aside_embryo("s1", "embryo_2", {"by": "kesavan"})
    store.register_embryo("s1", "embryo_2", position_coarse={"x": 5.0, "y": 6.0})
    experiment = ExperimentState()
    sessions._resume_session("s1", experiment)
    assert "embryo_2" in experiment.embryos
