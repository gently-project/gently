"""The agent can ask a person, and a person can ask the agent.

"let the agent tag people and add @agent". Tagging was a channel between
people only: a note of the agent's that wrote "@ryan" reached nobody, and
"@agent" in a person's line was dropped as a word that names no one.

Now a note the agent writes asks whoever it names, and a line that asks the
agent gets a line back, on the same session, for the one who asked. The
reply is read from the notes filed there and touches nothing else.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import gently.app.tools.memory_tools  # noqa: F401  registers the tools
from gently.core.file_store import FileStore
from gently.harness.memory import notebook_ask
from gently.harness.memory.file_store import FileContextStore
from gently.harness.tools.registry import get_tool_registry
from gently.ui.web import auth
from gently.ui.web.routes import inbox as inbox_routes
from gently.ui.web.routes import notebook as notebook_routes


def _rig(tmp_path, monkeypatch, answer):
    store = FileStore(tmp_path)
    cs = FileContextStore(tmp_path / "agent")
    server = MagicMock()
    server.context_store = cs
    server.gently_store = store
    server.agent_bridge.agent.store = store
    monkeypatch.setattr(inbox_routes, "known_people", lambda _server: ["ryan", "kesavan"])
    asked: list[tuple[str, list[str]]] = []

    async def fake(client, model, question, notes, history=None):
        asked.append((question, [n.body for n in notes]))
        if isinstance(answer, Exception):
            raise answer
        return {"answer": answer, "points": [{"text": "x", "note_ids": [notes[0].id]}]}

    monkeypatch.setattr(notebook_ask, "answer_question", fake)
    app = FastAPI()
    app.include_router(notebook_routes.create_router(server))
    app.include_router(inbox_routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True

    def as_(me):
        c = TestClient(app)
        c.cookies.set("gently_operator", me)
        return c

    store.create_session("s1", name="monday")
    return as_, cs, asked


def test_a_line_that_asks_the_agent_gets_a_line_back_for_the_one_who_asked(tmp_path, monkeypatch):
    as_, cs, asked = _rig(tmp_path, monkeypatch, "Three hatched, one did not.")
    as_("ryan").post(
        "/api/notebook/notes", json={"body": "three of four hatched", "sessions": ["s1"]}
    )
    k = as_("kesavan")
    ask = k.post(
        "/api/notebook/notes", json={"body": "@Agent, how many hatched?", "sessions": ["s1"]}
    ).json()["note"]
    assert ask["mentions"] == ["agent"]

    # It was asked the question without its own name, over the notes filed
    # there, and not over the question itself.
    assert asked == [("how many hatched?", ["three of four hatched"])]
    reply = next(n for n in cs.notebook.query_notes(session="s1") if n.author.value == "agent")
    assert reply.body == "Three hatched, one did not."
    assert reply.sessions == ["s1"] and reply.mentions == ["kesavan"] and reply.by is None
    assert len(reply.basis) == 1

    # The one who asked finds it in their inbox, and their ask is answered by the agent.
    box = k.get("/api/inbox").json()
    assert [i["note"]["id"] for i in box["asks"]] == [reply.id]
    assert box["mine"][0]["answered_by"] == ["agent"]
    # Nobody else was asked anything, and the agent's line asks the agent nothing.
    assert as_("ryan").get("/api/inbox").json()["new"] == []
    assert len(asked) == 1


def test_a_line_that_does_not_ask_it_is_not_answered(tmp_path, monkeypatch):
    as_, cs, asked = _rig(tmp_path, monkeypatch, "never")
    as_("kesavan").post(
        "/api/notebook/notes", json={"body": "the agent was off; @ryan look", "sessions": ["s1"]}
    )
    assert asked == [] and len(cs.notebook.query_notes()) == 1


def test_when_it_cannot_answer_it_says_so_and_the_line_stays_out_of_the_notebook(
    tmp_path, monkeypatch
):
    as_, cs, _ = _rig(tmp_path, monkeypatch, RuntimeError("no key"))
    k = as_("kesavan")
    k.post("/api/notebook/notes", json={"body": "set up", "sessions": ["s1"]})
    k.post("/api/notebook/notes", json={"body": "@agent what happened?", "sessions": ["s1"]})
    reply = next(n for n in cs.notebook.query_notes() if n.author.value == "agent")
    assert reply.body == "I could not answer this: RuntimeError."
    assert reply.in_notebook is False  # the agent does not read its own failure later
    assert [i["note"]["id"] for i in k.get("/api/inbox").json()["asks"]] == [reply.id]


def test_a_note_the_agent_writes_asks_the_people_it_names(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox_routes, "known_people", lambda _server: ["ryan", "kesavan"])
    cs = FileContextStore(tmp_path / "agent")
    agent = SimpleNamespace(context_store=cs, session_id="s1", memory=None, store=None)
    reg = get_tool_registry()
    asyncio.run(
        reg.get("propose_finding").handler(
            text="Hatching is 18 % faster at 25 C. @Ryan can you confirm on e03?",
            context={"agent": agent},
        )
    )
    asyncio.run(
        reg.get("record_note").handler(text="ask @nobody about it", context={"agent": agent})
    )
    finding, plain = sorted(cs.notebook.query_notes(), key=lambda n: n.created_at)
    assert finding.mentions == ["ryan"] and plain.mentions == []
    # It is in Ryan's inbox, as the agent's.
    box = inbox_routes.inbox_for(None, cs, "ryan")
    assert [i["note"]["id"] for i in box["new"]] == [finding.id]
    assert inbox_routes.who_wrote(finding) == "agent"


def test_the_box_offers_the_agent_and_the_inbox_names_it():
    from pathlib import Path

    js = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
    utils = (js / "utils.js").read_text(encoding="utf-8")
    inbox = (js / "inbox.js").read_text(encoding="utf-8")
    assert "{ id: 'agent', name: 'agent' }]" in utils
    assert "const by = n => (n.author === 'agent' ? 'agent' : n.by);" in inbox
    assert "Who.head(i.note.by)" not in inbox
