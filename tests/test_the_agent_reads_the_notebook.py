"""The agent reads the notebook, questions are in it, and a replaced finding
says what replaced it.

From an audit of the notebook against its design ("a memory the agent and
the lab build together"): the agent was told a project's top five findings
and nothing else of the notebook, and its recall tools read the older
stores; a question went to a ledger of its own and the notebook's question
kind stayed empty; and replacing a finding marked the old one superseded
without recording its successor.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import gently.app.tools.memory_tools  # noqa: F401  registers the tools
from gently.harness.memory.file_store import FileContextStore
from gently.harness.memory.model import Question
from gently.harness.memory.notebook import Author, Note, NoteKind, NoteStatus
from gently.harness.tools.registry import get_tool_registry
from gently.ui.web import auth
from gently.ui.web.routes import inbox as inbox_routes
from gently.ui.web.routes import notebook as notebook_routes


def _tool(name):
    return get_tool_registry().get(name).handler


def _line(cs, body, **kw):
    kw.setdefault("author", Author.HUMAN)
    return cs.notebook.write_note(
        Note(id="", kind=kw.pop("kind", NoteKind.OBSERVATION), body=body, **kw)
    )


def test_the_agent_can_read_what_was_written(tmp_path):
    cs = FileContextStore(tmp_path / "agent")
    agent = SimpleNamespace(context_store=cs, session_id="s1", memory=None, store=None)
    a = _line(cs, "three of four hatched", by="ryan", sessions=["s1"])
    _line(cs, "twitching at 370 min", by="kesavan", sessions=["s2"])
    aside = _line(cs, "hatched, but ignore this", by="ryan", sessions=["s1"])
    cs.notebook.set_in_notebook(aside, False)
    read = _tool("read_notebook")

    out = asyncio.run(read(query="hatched", context={"agent": agent}))
    # The note, who wrote it, and its id to cite; not the one set aside.
    assert f"[{a}]" in out and "ryan" in out and "three of four hatched" in out
    assert "ignore this" not in out and "twitching" not in out

    here = asyncio.run(read(session="current", context={"agent": agent}))
    assert "three of four hatched" in here and "twitching" not in here
    assert asyncio.run(read(query="zebra", context={"agent": agent})) == (
        "Nothing in the notebook matches."
    )
    few = asyncio.run(read(limit=1, context={"agent": agent}))
    assert "and 1 older" in few


def test_a_question_is_a_note_and_its_answer_is_a_line_resting_on_it(tmp_path):
    cs = FileContextStore(tmp_path / "agent")
    q = Question(id="q1234567", content="Does orientation change the twitch time?", project_id="p1")
    cs.add_question(q, by="kesavan", mentions=["ryan"])

    note = cs.notebook.get_note("q1234567")
    assert note.kind == NoteKind.QUESTION and note.status == NoteStatus.OPEN
    assert note.by == "kesavan" and note.projects == ["p1"] and note.mentions == ["ryan"]
    # The ledger the Projects tab reads is unchanged.
    assert [x.id for x in cs.get_open_questions()] == ["q1234567"]

    cs.resolve_question("q1234567", "No: within a minute either way.", by="ryan")
    assert cs.notebook.get_note("q1234567").status == NoteStatus.ANSWERED
    answer = next(n for n in cs.notebook.query_notes() if n.basis == ["q1234567"])
    assert answer.body == "No: within a minute either way." and answer.by == "ryan"
    assert answer.projects == ["p1"]
    assert cs.get_open_questions() == []

    # The agent's own question is the agent's note.
    agent = SimpleNamespace(context_store=cs, session_id=None, memory=None, store=None)
    asyncio.run(_tool("raise_question")(content="Why did e5 arrest?", context={"agent": agent}))
    mine = [n for n in cs.notebook.query_notes(kind=NoteKind.QUESTION) if n.author == Author.AGENT]
    assert [n.body for n in mine] == ["Why did e5 arrest?"]


def test_a_replaced_finding_points_at_the_one_that_replaced_it(tmp_path, monkeypatch):
    cs = FileContextStore(tmp_path / "agent")
    server = MagicMock()
    server.context_store = cs
    server.gently_store = None
    monkeypatch.setattr(inbox_routes, "known_people", lambda _server: [])
    app = FastAPI()
    app.include_router(notebook_routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    c = TestClient(app)
    old = _line(cs, "18 % faster at 25 C", kind=NoteKind.FINDING, projects=["p1"])

    r = c.post(f"/api/notebook/notes/{old}/supersede", json={"body": "12 % faster, n=9"})
    assert r.status_code == 200
    new = r.json()["note"]
    assert new["kind"] == "finding" and new["basis"] == [old] and new["projects"] == ["p1"]
    was = cs.notebook.get_note(old)
    assert was.status == NoteStatus.SUPERSEDED and was.superseded_by == new["id"]
    assert {"rel": "refines", "to": old} in [
        {"rel": link.get("rel"), "to": link.get("to")}
        for link in cs.notebook.get_note(new["id"]).links
    ]
    assert c.post("/api/notebook/notes/nope/supersede", json={"body": "x"}).status_code == 404
    assert c.post(f"/api/notebook/notes/{old}/supersede", json={"body": " "}).status_code == 400


def test_the_page_replaces_in_one_call_and_shows_the_successor():
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
    campaigns = (js / "campaigns.js").read_text(encoding="utf-8")
    assert "/supersede`, { body: d.body });" in campaigns
    assert "{ status: 'superseded' });" not in campaigns
    assert "replaced by ${cites([n.superseded_by])}" in campaigns
