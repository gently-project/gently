"""Tests for the ELN Experiment store (FileContextStore, spine phase 2)."""

from gently.harness.memory.file_store import FileContextStore


def test_create_and_get_experiment(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    eid = s.create_experiment(
        "32C vs control",
        arms=[{"name": "hot", "strain_ref": "OH904", "condition": "25C"}],
        controls=["control"],
    )
    e = s.get_experiment(eid)
    assert e["title"] == "32C vs control"
    assert e["arms"][0]["name"] == "hot"
    assert e["arms"][0]["strain_ref"] == "OH904"
    assert e["controls"] == ["control"]


def test_arm_strain_alias(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    eid = s.create_experiment("e", arms=[{"name": "a", "strain": "N2", "condition": "c"}])
    assert s.get_experiment(eid)["arms"][0]["strain_ref"] == "N2"  # `strain` → strain_ref


def test_link_session_to_arm(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    eid = s.create_experiment("e", arms=[{"name": "hot", "strain_ref": "x", "condition": "c"}])
    assert s.link_session_to_arm(eid, "hot", "sess1") is True
    assert "sess1" in s.get_experiment(eid)["arms"][0]["session_ids"]
    assert s.link_session_to_arm(eid, "missing", "sess1") is False
    # idempotent
    s.link_session_to_arm(eid, "hot", "sess1")
    assert s.get_experiment(eid)["arms"][0]["session_ids"].count("sess1") == 1


def test_list_experiments(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_experiment("a")
    s.create_experiment("b")
    assert len(s.list_experiments()) == 2
