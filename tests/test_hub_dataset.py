"""The brightfield exports as one Hugging Face dataset.

"can we add the bright field data in to hugging face repo? structure it
well". No upload here: what goes where, the table, the card, and the
frame table in the Hub's shape are all decided from the export folders.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest
import yaml

pytest.importorskip("tifffile")

from gently.core.hub_dataset import (  # noqa: E402
    dataset_card,
    discover,
    field_metadata_csv,
    plan,
    sessions_rows,
    write_sessions_csv,
)


def _export(
    tmp_path, folder="20261007_1833_two_b1ffda4e", fields=(1, 2), frames=3, embryos=("embryo_1",)
):
    """An export folder as gently.core.export lays it out, small."""
    import tifffile

    root = tmp_path / folder
    (root / "metadata").mkdir(parents=True)
    (root / "metadata" / "session.yaml").write_text(
        yaml.safe_dump(
            {
                "session_id": folder.split("_")[-1],
                "name": "two fields",
                "created_at": "2026-10-07T18:33:00",
                "description": "an overnight",
            }
        ),
        encoding="utf-8",
    )
    for name in ("README.txt", "embryos.csv", "events.csv"):
        (root / name).write_text(name, encoding="utf-8")
    (root / "embryo_1" / "volumes").mkdir(parents=True)
    (root / "embryo_1" / "volumes" / "embryo_1_t0001.tif").write_bytes(b"not for the hub")
    dic = root / "dic"
    for n in fields:
        fd = dic / f"field_{n}" if len(fields) > 1 else dic
        fd.mkdir(parents=True, exist_ok=True)
        rows = []
        for i in range(1, frames + 1):
            name = f"dic_f{i:04d}_20261007-18{i:02d}00.tif"
            tifffile.imwrite(fd / name, np.zeros((4, 6), dtype=np.uint16))
            rows.append(
                {
                    "file": f"dic/{f'field_{n}/' if len(fields) > 1 else ''}{name}",
                    "frame": i,
                    "field": n,
                    "captured_at": f"2026-10-07T18:{i:02d}:00",
                    "x_um": -1.0,
                    "dark": "../references/r/dark.tif",
                }
            )
        with open(fd / "dic.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        for e in embryos:
            (fd / "embryos" / e / "raw").mkdir(parents=True)
    return root


class TestWhatIsThere:
    def test_an_export_is_read_from_its_files(self, tmp_path):
        s = discover(_export(tmp_path))
        assert (
            s.session_id == "b1ffda4e"
            and s.name == "two fields"
            and s.created.startswith("2026-10-07")
        )
        assert [f.number for f in s.fields] == [1, 2] and [f.rel for f in s.fields] == [
            "field_1",
            "field_2",
        ]
        assert s.frames == 6 and s.embryos == ["embryo_1"]

    def test_a_single_field_export_has_one_field_at_dic_itself(self, tmp_path):
        s = discover(_export(tmp_path, folder="20261006_1001_one_d4f9ebe1", fields=(1,)))
        assert len(s.fields) == 1 and s.fields[0].rel == "" and s.fields[0].folder.name == "dic"

    def test_not_an_export(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            discover(tmp_path)


class TestWhatGoesWhere:
    def test_the_record_and_the_dic_folder_never_the_volumes(self, tmp_path):
        s = discover(_export(tmp_path))
        where = plan([s])
        in_repo = [r for _, r in where]
        assert "sessions/20261007_1833_two_b1ffda4e/dic" in in_repo
        assert "sessions/20261007_1833_two_b1ffda4e/metadata" in in_repo
        assert "sessions/20261007_1833_two_b1ffda4e/README.txt" in in_repo
        assert "sessions/20261007_1833_two_b1ffda4e/embryos.csv" in in_repo
        assert not any("volumes" in r or "embryo_1/" in r for r in in_repo)
        local = {r: p for p, r in where}
        assert local["sessions/20261007_1833_two_b1ffda4e/dic"] == s.root / "dic"

    def test_the_fields_frame_table_in_the_hubs_shape(self, tmp_path):
        s = discover(_export(tmp_path))
        out = field_metadata_csv(s.fields[0].folder)
        assert out == s.fields[0].folder / "metadata.csv"
        rows = list(csv.DictReader(open(out, encoding="utf-8")))
        assert [r["file_name"] for r in rows] == [
            f"dic_f000{i}_20261007-180{i}00.tif" for i in (1, 2, 3)
        ]
        assert (
            "file" not in rows[0]
            and rows[0]["frame"] == "1"
            and rows[0]["dark"] == "../references/r/dark.tif"
        )
        # every file_name is a file in that folder: the loader's contract
        assert all((s.fields[0].folder / r["file_name"]).is_file() for r in rows)
        assert field_metadata_csv(tmp_path) is None

    def test_the_table_of_sessions(self, tmp_path):
        a = discover(_export(tmp_path))
        b = discover(
            _export(
                tmp_path,
                folder="20261006_1001_one_d4f9ebe1",
                fields=(1,),
                frames=2,
                embryos=("embryo_1", "embryo_2"),
            )
        )
        rows = sessions_rows([a, b])
        assert [r["session"] for r in rows] == [
            "20261007_1833_two_b1ffda4e",
            "20261006_1001_one_d4f9ebe1",
        ]
        assert (
            rows[0]["fields"] == 2
            and rows[0]["frames"] == 6
            and rows[1]["embryos"] == "embryo_1 embryo_2"
        )
        p = write_sessions_csv([a, b], tmp_path / "sessions.csv")
        assert len(list(csv.DictReader(open(p, encoding="utf-8")))) == 2


class TestTheCard:
    def test_front_matter_and_the_parts_a_reader_needs(self, tmp_path):
        s = discover(_export(tmp_path))
        card = dataset_card([s], "gently-project/celegans-brightfield", "cc-by-4.0")
        head, body = card.split("---\n", 2)[1:]
        meta = yaml.safe_load(head)
        assert (
            meta["license"] == "cc-by-4.0"
            and "microscopy" in meta["tags"]
            and meta["size_categories"] == ["n<1K"]
        )
        assert "| `20261007_1833_two_b1ffda4e` | two fields |" in body
        assert "(raw - dark) / (flat - dark)" in body
        assert (
            'load_dataset("imagefolder", data_dir="sessions/20261007_1833_two_b1ffda4e/dic/'
            'field_1/embryos/embryo_1")' in body
        )
        assert 'data_dir="sessions/20261007_1833_two_b1ffda4e/dic/field_1")' in body
        assert "gently-project/celegans-brightfield" in body

    def test_the_tool_plans_without_the_hub(self, tmp_path, capsys):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "hf_tool", Path(__file__).resolve().parents[1] / "tools" / "hf_brightfield_dataset.py"
        )
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        root = _export(tmp_path)
        assert mod.main(["plan", str(root), "--repo", "org/name"]) == 0
        out = capsys.readouterr().out
        assert "sessions/20261007_1833_two_b1ffda4e/dic" in out and "<- written at upload" in out
        assert not (root / "dic" / "field_1" / "metadata.csv").exists(), "plan writes nothing"
