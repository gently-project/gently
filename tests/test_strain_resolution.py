"""Tests for display-side strain resolution (non-mutating, bare-string safe)."""

from gently.eln.strain_resolution import enrich_imaging_spec, resolve_ref
from gently.harness.memory.file_store import FileContextStore


def test_resolve_ref_record_and_shim(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_strain("OH904", genotype="otIs355")
    assert resolve_ref(s, "OH904")["genotype"] == "otIs355"  # real record
    assert resolve_ref(s, "unknown-str") == {"name": "unknown-str"}  # bare-string shim
    assert resolve_ref(s, None) is None


def test_enrich_imaging_spec_non_mutating(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_strain("N2")
    spec = {"strain": "N2", "num_slices": 80}
    out = enrich_imaging_spec(s, spec)
    assert out["strain"] == "N2"  # original preserved
    assert out["strain_record"]["name"] == "N2"
    assert "strain_record" not in spec  # did not mutate input
