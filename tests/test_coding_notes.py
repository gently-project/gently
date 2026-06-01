import json
from types import SimpleNamespace

import pytest

from gently.app.tools.coding_notes_tools import (
    leave_coding_agent_note,
    list_coding_agent_notes,
)
from gently.core.file_store import FileStore
from gently.harness.coding_notes import CodingNotesStore


def test_coding_notes_store_appends_and_lists_newest_first(tmp_path):
    store = CodingNotesStore(tmp_path / "notes.jsonl")

    first = store.append_note("First note", session_id="s1", category="bug")
    second = store.append_note("Second note", session_id="s1", category="feedback")

    notes = store.list_notes()
    raw = [
        json.loads(line)
        for line in (tmp_path / "notes.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [note.note_id for note in notes] == [second.note_id, first.note_id]
    assert raw[0]["message"] == "First note"
    assert store.list_notes(category="bug")[0].message == "First note"


def test_coding_notes_store_rejects_empty_messages(tmp_path):
    store = CodingNotesStore(tmp_path / "notes.jsonl")

    with pytest.raises(ValueError, match="cannot be empty"):
        store.append_note("   ")


@pytest.mark.asyncio
async def test_leave_coding_agent_note_tool_writes_to_session_dir(tmp_path):
    file_store = FileStore(tmp_path)
    file_store.create_session("abc12345", name="notes")
    agent = SimpleNamespace(
        store=file_store,
        session_id="abc12345",
        storage_path=tmp_path,
    )

    result = await leave_coding_agent_note(
        message="The Gently agent should surface detector errors to the user.",
        category="bug",
        severity="warning",
        context_summary="Detector returned an exception during detection.",
        context={"agent": agent},
    )

    session_dir = file_store._session_dir("abc12345")
    notes_path = session_dir / "coding_agent_notes.jsonl"
    payload = json.loads(notes_path.read_text(encoding="utf-8").strip())

    assert "Saved coding-agent note" in result
    assert payload["session_id"] == "abc12345"
    assert payload["category"] == "bug"
    assert payload["source"] == "gently_agent"
    assert payload["context"]["summary"].startswith("Detector returned")


@pytest.mark.asyncio
async def test_list_coding_agent_notes_tool_formats_recent_notes(tmp_path):
    agent = SimpleNamespace(
        store=None,
        session_id=None,
        storage_path=tmp_path,
    )
    store = CodingNotesStore.for_agent(agent)
    store.append_note("Remember to add a regression test.", category="test")

    result = await list_coding_agent_notes(limit=5, context={"agent": agent})

    assert "Remember to add a regression test." in result
    assert str(tmp_path / "coding_agent_notes.jsonl") in result
