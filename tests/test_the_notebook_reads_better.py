"""The Notebook tab after an audit of how it is used.

On the rig every one of 22 notes was a line written on a session. So: each
project's page read 0 (a session's line carried no project); the box to
write in sat under all 22 cards, three screens down; no card said when it
was written; nothing could be searched; and every card wore the same two
labels, OBSERVATION and CONFIRMED, which told nobody anything.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core.file_store import FileStore
from gently.harness.memory.file_store import FileContextStore
from gently.ui.web import auth
from gently.ui.web.routes import inbox as inbox_routes
from gently.ui.web.routes import notebook as notebook_routes

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
JS = (WEB / "static" / "js" / "notebook.js").read_text(encoding="utf-8")


def test_a_line_on_a_session_is_on_that_sessions_project(tmp_path, monkeypatch):
    store = FileStore(tmp_path)
    cs = FileContextStore(tmp_path / "agent")
    server = MagicMock()
    server.context_store = cs
    server.gently_store = store
    monkeypatch.setattr(inbox_routes, "known_people", lambda _server: [])
    app = FastAPI()
    app.include_router(notebook_routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    c = TestClient(app)

    store.create_session("s1", name="filed")
    store.create_session("s2", name="loose")
    monkeypatch.setattr(store, "session_links", lambda sid: [{"id": "p1"}] if sid == "s1" else [])

    def write(**body):
        return c.post("/api/notebook/notes", json=body).json()["note"]

    assert write(body="hatched", sessions=["s1"])["projects"] == ["p1"]
    assert write(body="no project", sessions=["s2"])["projects"] == []
    # A project that was named is kept; a line on no session has none.
    assert write(body="other", sessions=["s1"], projects=["p9"])["projects"] == ["p9"]
    assert write(body="general")["projects"] == []
    assert [n.body for n in cs.notebook.query_notes(project="p1")] == ["hatched"]


def test_the_box_and_the_conversation_are_above_the_notes():
    tab = INDEX[INDEX.index('<div id="notebook-content"') : INDEX.index("<!-- Devices Tab -->")]
    assert tab.index('class="nb-ask"') < tab.index('id="nb-conv"') < tab.index('id="nb-notes"')
    assert tab.count('id="nb-ask-input"') == 1


def test_a_card_says_when_and_wears_a_label_only_when_it_tells_something():
    assert "whenEl.textContent = when(n.created_at);" in JS
    assert "badge.hidden = n.kind === 'observation';" in JS
    assert "status.textContent = n.status === 'confirmed' ? '' : (n.status || '');" in JS


def test_the_notes_on_a_page_can_be_searched():
    assert 'id="nb-search"' in INDEX
    assert "search.addEventListener('input', () => renderNotes(_shown));" in JS
    assert "words.every(w => hay.includes(w))" in JS
