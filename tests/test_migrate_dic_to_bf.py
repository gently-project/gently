"""The on-disk rename of the brightfield overview's old name, ``dic`` → ``bf``.

The code was renamed without a read-side shim, so what a session already
holds has to be renamed too (gently/core/migrations.py, run at boot;
tools/migrate_dic_to_bf.py by hand). The pass is exercised on a small fake
root: a snapshot pair, the session's plan and checkpoint, a timeline, and an
agent plan — and the words it must not touch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gently.core import migrations as mig

LAUNCH = (Path(__file__).resolve().parents[1] / "launch_gently.py").read_text(encoding="utf-8")


@pytest.fixture
def root(tmp_path):
    sd = tmp_path / "sessions" / "20261007_1833_unnamed_b1ffda4e"
    snaps = sd / "snapshots"
    snaps.mkdir(parents=True)
    (snaps / "dic_00034cf0175a.tif").write_bytes(b"II*\x00tif")
    (snaps / "dic_00034cf0175a.meta.yaml").write_text(
        "session_id: b1ffda4e\nsource: dic\n"
        "file_path: D:\\Gently3\\sessions\\x\\snapshots\\dic_00034cf0175a.tif\n"
        "metadata:\n  channel: dic\n  frame: 162\n  periodic: true\n",
        encoding="utf-8",
    )
    (snaps / "spim_aaaa.tif").write_bytes(b"II*\x00tif")
    (sd / "acquisition.yaml").write_text(
        "cadence_s: 30\ndic:\n  enabled: true\n  light: led\nstop_conditions: {}\n",
        encoding="utf-8",
    )
    (sd / "timelapse.yaml").write_text(
        "dic:\n  enabled: true\ndic_frames: 1363\ndic_last_at: '2026-10-08'\n"
        "embryos: {}\nindicator: dict\n",
        encoding="utf-8",
    )
    (sd / "timeline.jsonl").write_text(
        json.dumps({"data": {"dic": {"enabled": True}, "dic_frames": 2, "predicted": "dict"}})
        + "\n",
        encoding="utf-8",
    )
    (sd / "conversation.json").write_text('{"text": "the dic frames"}', encoding="utf-8")
    plans = tmp_path / "agent" / "operation_plans"
    plans.mkdir(parents=True)
    (plans / "b1ffda4e.yaml").write_text(
        "structure:\n  dic:\n    enabled: true\n", encoding="utf-8"
    )
    return tmp_path


def test_the_token_rule_leaves_other_words_alone():
    text, n = mig.rewrite_text("dic: 1\ndic_frames: 2\nindicator: dict\nperiodic: x\n'dic'\n")
    assert text == "bf: 1\nbf_frames: 2\nindicator: dict\nperiodic: x\n'bf'\n"
    assert n == 3


def test_a_dry_run_changes_nothing(root):
    m = mig.Migration(root, apply=False)
    m.run()
    assert (m.renamed, m.rewritten) == (2, 5)
    snaps = root / "sessions" / "20261007_1833_unnamed_b1ffda4e" / "snapshots"
    assert (snaps / "dic_00034cf0175a.tif").exists()
    assert not (root / "_migration_backup").exists()
    assert not (root / "migrate_dic_to_bf.log.jsonl").exists()


def test_apply_renames_rewrites_backs_up_and_logs(root):
    m = mig.Migration(root, apply=True)
    m.run()
    sd = root / "sessions" / "20261007_1833_unnamed_b1ffda4e"
    snaps = sd / "snapshots"
    assert sorted(p.name for p in snaps.iterdir()) == [
        "bf_00034cf0175a.meta.yaml",
        "bf_00034cf0175a.tif",
        "spim_aaaa.tif",
    ]
    meta = (snaps / "bf_00034cf0175a.meta.yaml").read_text(encoding="utf-8")
    assert "source: bf\n" in meta and "channel: bf\n" in meta
    assert "snapshots\\bf_00034cf0175a.tif" in meta
    assert "periodic: true" in meta
    assert (sd / "acquisition.yaml").read_text(encoding="utf-8").startswith("cadence_s: 30\nbf:\n")
    tl = (sd / "timelapse.yaml").read_text(encoding="utf-8")
    assert tl.startswith("bf:\n") and "bf_frames: 1363" in tl and "indicator: dict" in tl
    ev = json.loads((sd / "timeline.jsonl").read_text(encoding="utf-8"))
    assert ev["data"] == {"bf": {"enabled": True}, "bf_frames": 2, "predicted": "dict"}
    # History is not rewritten.
    assert (sd / "conversation.json").read_text(encoding="utf-8") == '{"text": "the dic frames"}'
    plan = (root / "agent" / "operation_plans" / "b1ffda4e.yaml").read_text(encoding="utf-8")
    assert plan == "structure:\n  bf:\n    enabled: true\n"
    # Every rewritten file has its original under the backup, and the log says what happened.
    backup = root / "_migration_backup" / "sessions" / sd.name
    kept = (backup / "acquisition.yaml").read_text(encoding="utf-8")
    assert kept.startswith("cadence_s: 30\ndic:\n")
    assert (backup / "snapshots" / "dic_00034cf0175a.meta.yaml").exists()
    log_text = (root / "migrate_dic_to_bf.log.jsonl").read_text(encoding="utf-8")
    log = [json.loads(line) for line in log_text.splitlines()]
    assert sum(1 for r in log if r["op"] == "rename") == 2
    assert sum(1 for r in log if r["op"] == "rewrite") == 5


def test_running_twice_is_a_no_op(root):
    mig.Migration(root, apply=True).run()
    again = mig.Migration(root, apply=True)
    again.run()
    assert (again.renamed, again.rewritten) == (0, 0)


def test_at_boot_it_runs_once_and_leaves_a_sentinel(root):
    first = mig.migrate_dic_to_bf(root)
    assert first is not None and (first.renamed, first.rewritten) == (2, 5)
    assert (root / mig.SENTINEL).is_file()
    assert mig.migrate_dic_to_bf(root) is None, "walked the store again with the sentinel present"
    forced = mig.migrate_dic_to_bf(root, force=True)
    assert forced is not None and (forced.renamed, forced.rewritten) == (0, 0)


def test_launch_runs_it_before_anything_opens_the_store():
    """Nothing is running against the store at that point — the only safe time."""
    assert "migrate_dic_to_bf(storage_dir)" in LAUNCH
    assert LAUNCH.index("migrate_dic_to_bf(storage_dir)") < LAUNCH.index(
        "store = FileStore(storage_dir)"
    )
