"""Tests for the ELN seed-program loader."""

from pathlib import Path

from gently.eln.seed_loader import load_program, load_seed_dir
from gently.harness.memory.file_store import FileContextStore


def test_load_program(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    program = {
        "slug": "demo",
        "campaign": {"title": "T", "goal": "G", "description": "D"},
        "strains": [{"name": "OH904", "genotype": "otIs355"}],
        "experiments": [
            {"title": "E1", "arms": [{"name": "a", "strain": "OH904", "condition": "c"}]}
        ],
        "hypotheses": [{"statement": "H1", "predictions": ["p"]}],
    }
    out = load_program(s, program)
    assert s.get_campaign(out["campaign_id"]) is not None
    assert len(out["strain_ids"]) == 1
    assert len(out["experiment_ids"]) == 1
    e = s.get_experiment(out["experiment_ids"][0])
    assert e["arms"][0]["strain_ref"] == "OH904"
    h = s.get_hypothesis(out["hypothesis_ids"][0])
    assert h["predictions"][0]["target"] == "p"


def test_load_real_seed_dir():
    """The shipped seed/programs/ load without error into a fresh store."""
    import tempfile

    seed_dir = Path(__file__).resolve().parents[1] / "seed" / "programs"
    with tempfile.TemporaryDirectory() as td:
        s = FileContextStore(Path(td) / "agent")
        loaded = load_seed_dir(s, seed_dir)
        assert len(loaded) == 4                       # the 4 real programs
        assert len(s.list_experiments()) >= 4
        assert len(s.list_strains()) >= 4
