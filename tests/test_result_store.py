"""Tests for the ELN Result store (FileContextStore, spine phase 3)."""

from gently.eln.accuracy import accuracy_result
from gently.harness.memory.file_store import FileContextStore


def test_save_and_filter_results(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    r = accuracy_result(
        "sess", "emb",
        [{"timepoint": 1, "predicted_stage": "bean"}],
        [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 5}],
    )
    r["experiment_ref"] = "exp1"
    rid = s.save_result(r)
    got = s.get_result(rid)
    assert got["kind"] == "accuracy"
    assert got["experiment_ref"] == "exp1"
    assert len(s.list_results(experiment_ref="exp1")) == 1
    assert len(s.list_results(experiment_ref="other")) == 0
    assert len(s.list_results()) == 1
