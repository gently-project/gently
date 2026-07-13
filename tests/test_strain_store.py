"""Tests for the ELN Strain store (FileContextStore, spine phase 1).

Strain is an optional overlay with bare-string back-compat: a strain reference
that matches no record resolves to None so callers keep the display string.
"""

from gently.harness.memory.file_store import FileContextStore


def test_create_and_get_strain(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    sid = s.create_strain(
        "OH904", genotype="otIs355", markers=["rab-3p::GFP"], organism_ref="celegans"
    )
    rec = s.get_strain(sid)
    assert rec is not None
    assert rec["name"] == "OH904"
    assert rec["genotype"] == "otIs355"
    assert rec["markers"] == ["rab-3p::GFP"]
    assert rec["organism_ref"] == "celegans"


def test_list_strains(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_strain("A")
    s.create_strain("B")
    assert len(s.list_strains()) == 2


def test_resolve_strain_by_id_and_name(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    sid = s.create_strain("N2")
    assert s.resolve_strain(sid)["name"] == "N2"  # by id
    assert s.resolve_strain("n2")["id"] == sid  # case-insensitive name
    assert s.resolve_strain("nonexistent") is None  # bare string, no match → None
    assert s.resolve_strain(None) is None
