import json
from pathlib import Path

from gently.core.file_store import FileStore
from gently.debug import prepare_debug_context, resolve_session_dir


def _write_jsonl(path: Path, records):
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_prepare_debug_context_exports_session_bundle(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("abc12345", name="debug test")
    session_dir = store._session_dir("abc12345")
    assert session_dir is not None

    _write_jsonl(
        session_dir / "decisions.jsonl",
        [
            {
                "timestamp": "2026-05-30T12:00:00",
                "agent": "production",
                "trigger": "user_message",
                "tool_calls": [
                    {"name": "acquire_volume", "input": {"embryo_id": "embryo_1"}}
                ],
            }
        ],
    )
    _write_jsonl(
        session_dir / "events.jsonl",
        [{"event_type": "STAGE_MOVED", "data": {"x": 1}}],
    )

    bundle = prepare_debug_context(
        "abc12345",
        root=tmp_path,
        output_dir=tmp_path / "debug_out",
        annotation="should check stored position before acquisition",
    )

    output_dir = Path(bundle.output_dir)
    context = (output_dir / "debug_context.md").read_text(encoding="utf-8")
    source_files = (output_dir / "source_files.txt").read_text(encoding="utf-8")
    artifacts = json.loads((output_dir / "artifacts.json").read_text(encoding="utf-8"))
    transcript = (output_dir / "transcript_excerpt.jsonl").read_text(encoding="utf-8")

    assert "should check stored position" in context
    assert "gently/app/tools/acquisition_tools.py" in source_files
    assert artifacts["session_id"] == "abc12345"
    assert "acquire_volume" in transcript


def test_resolve_session_dir_accepts_prefix(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("prefix123", name="debug test")

    session_id, session_dir = resolve_session_dir("prefix", root=tmp_path)

    assert session_id == "prefix123"
    assert session_dir.exists()
