"""Tests for the ELN Hypothesis store (FileContextStore, spine phase 3)."""

import pytest

from gently.harness.memory.file_store import FileContextStore


def test_create_get_hypothesis(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    hid = s.create_hypothesis(
        "25C shifts hatching-time distribution later",
        predictions=[{"target": "median_hatch", "expected": "+30min"}],
        author="human",
    )
    h = s.get_hypothesis(hid)
    assert h["statement"].startswith("25C")
    assert h["status"] == "proposed"
    assert h["predictions"][0]["target"] == "median_hatch"
    assert h["author"] == "human"


def test_set_status(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    hid = s.create_hypothesis("h")
    assert s.set_hypothesis_status(hid, "supported") is True
    assert s.get_hypothesis(hid)["status"] == "supported"
    with pytest.raises(ValueError):
        s.set_hypothesis_status(hid, "bogus")
    assert s.set_hypothesis_status("nope", "refuted") is False


def test_list_hypotheses(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_hypothesis("a")
    s.create_hypothesis("b")
    assert len(s.list_hypotheses()) == 2
