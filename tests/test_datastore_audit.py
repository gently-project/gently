import json

from gently.core.datastore_audit import audit_datastore, format_audit_markdown


def test_datastore_audit_counts_artifacts_and_flags_missing_sidecars(tmp_path):
    session_dir = tmp_path / "sessions" / "20260601_test_abc12345"
    volume_dir = session_dir / "embryos" / "embryo_1" / "volumes"
    snapshot_dir = session_dir / "snapshots"
    trace_dir = session_dir / "embryos" / "embryo_1" / "traces"
    volume_dir.mkdir(parents=True)
    snapshot_dir.mkdir(parents=True)
    trace_dir.mkdir(parents=True)

    (session_dir / "session.yaml").write_text("session_id: abc12345\n", encoding="utf-8")
    (session_dir / "timeline.jsonl").write_text("{}\n", encoding="utf-8")
    (session_dir / "interaction_log.jsonl").write_text("{}\n", encoding="utf-8")
    (session_dir / "embryos" / "embryo_1" / "embryo.yaml").write_text(
        "embryo_id: embryo_1\n",
        encoding="utf-8",
    )
    (volume_dir / "t0001.tif").write_bytes(b"fake-tif")
    (snapshot_dir / "bottom_test.tif").write_bytes(b"fake-tif")
    (snapshot_dir / "bottom_test.meta.yaml").write_text("source: bottom\n", encoding="utf-8")
    (trace_dir / "t0001.json").write_text(json.dumps({"ok": True}), encoding="utf-8")
    (tmp_path / "agent" / "campaigns" / "c1" / "plan").mkdir(parents=True)
    (tmp_path / "agent" / "campaigns" / "c1" / "plan" / "current.yaml").write_text(
        "[]\n",
        encoding="utf-8",
    )

    report = audit_datastore(tmp_path)
    markdown = format_audit_markdown(report)

    assert report.session_count == 1
    assert report.artifact_counts["volumes"] == 1
    assert report.artifact_counts["volume_metadata"] == 0
    assert report.artifact_counts["snapshots"] == 1
    assert report.artifact_counts["snapshot_metadata"] == 1
    assert report.artifact_counts["campaign_plans"] == 1
    assert any("volume missing metadata sidecar" in gap for gap in report.gaps)
    assert "Artifact Counts" in markdown


def test_datastore_audit_flags_missing_sessions_directory(tmp_path):
    report = audit_datastore(tmp_path)

    assert report.session_count == 0
    assert any("missing sessions directory" in gap for gap in report.gaps)
