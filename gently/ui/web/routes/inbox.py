"""The asks addressed to a person: lines on sessions and projects that name
them with @.

Nothing here is a second record. An ask is a notebook note with the person
in its ``mentions``; whether it is done is read off what that person wrote
on the same session or project afterwards, a line of their own or a tool
note from saving marks. The one thing written is which asks they have
opened: ``agent/people/{id}/seen.yaml``, one small file per person. So the
list survives restarts and browsers, and nothing in it can go stale.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Request

from gently.core.file_store import _read_yaml, _write_yaml, one_writer
from gently.harness.memory.notebook import Author, Note, note_to_dict
from gently.ui.web.auth import current_username

AGENT = "agent"  # what a line writes to ask it: "@agent ..."


def who_wrote(n: Note) -> str | None:
    """Who a line is by, as a conversation counts them: the person, or the
    agent, whose lines carry no ``by``."""
    return AGENT if n.author == Author.AGENT else n.by


def known_people(server: Any) -> list[str]:
    """Ids a line can ask: the account names when there are accounts, else
    the operators this rig has seen. The same list /api/auth/users shows."""
    from gently.ui.web.accounts import get_account_store
    from gently.ui.web.operators import list_operators

    acc = get_account_store()
    if acc is not None and acc.has_users():
        return [str(u["username"]) for u in acc.list_users()]
    return [str(u["id"]) for u in list_operators(getattr(server, "gently_store", None))]


def _seen_path(cs: Any, pid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", pid)
    return Path(cs.agent_dir) / "people" / safe / "seen.yaml"


def read_seen(cs: Any, pid: str) -> set[str]:
    doc = _read_yaml(_seen_path(cs, pid)) or {}
    return {str(x) for x in (doc.get("seen") or [])}


@one_writer
def mark_seen(cs: Any, pid: str, ids: list[str]) -> set[str]:
    """Remember that this person has opened these asks. Ids of notes that no
    longer exist stay in the file; they match nothing and cost nothing."""
    seen = read_seen(cs, pid) | {str(x) for x in ids if x}
    _write_yaml(
        _seen_path(cs, pid),
        {"seen": sorted(seen), "at": datetime.now().isoformat(timespec="seconds")},
    )
    return seen


def _item(store: Any, cs: Any, n: Note) -> dict:
    sid = n.sessions[0] if n.sessions else None
    sess = (store.get_session(sid) or {}) if (sid and store is not None) else {}
    pid = n.projects[0] if n.projects else None
    if pid is None and sid and store is not None:
        links = store.session_links(sid)
        pid = links[0].get("id") if links else None
    c = cs.get_campaign(pid) if pid else None
    return {
        "note": note_to_dict(n),
        "session": {"id": sid, "name": sess.get("name")} if sid else None,
        "project": {"id": c.id, "name": c.shorthand or c.description} if c is not None else None,
    }


def _when_written(n: Note) -> datetime:
    """When a line counts as written. A plain line is written once, at its
    created_at; a titled line is a tool's, rewritten in place on every save,
    so its latest save is the moment that counts."""
    return n.updated_at if n.title else n.created_at


def _wrote_after(notes: list[Note], who: str, ask: Note) -> bool:
    """Did ``who`` write on the ask's session or project after it was asked?
    A line of their own or a tool note, either counts as an answer."""
    if ask.sessions:
        where = set(ask.sessions)
        return any(
            who_wrote(n) == who and _when_written(n) > ask.created_at and set(n.sessions) & where
            for n in notes
        )
    if ask.projects:
        where = set(ask.projects)
        return any(
            who_wrote(n) == who and _when_written(n) > ask.created_at and set(n.projects) & where
            for n in notes
        )
    return False


def _same_place(n: Note, ask: Note) -> bool:
    if ask.sessions:
        return bool(set(n.sessions) & set(ask.sessions))
    return bool(ask.projects) and bool(set(n.projects) & set(ask.projects))


def _replies(everything: list[Note], pid: str) -> dict[str, str]:
    """Lines that are for ``pid`` without naming them: ``{note id: ask id}``.
    An ask makes a conversation of the one who asked and the people asked;
    what any of them then writes on that session or project is for the
    others. Kesavan asks @ryan, Ryan answers without an @: it is Kesavan's."""
    out: dict[str, str] = {}
    for ask in everything:
        people = {who_wrote(ask), *ask.mentions} - {None}
        if not ask.mentions or pid not in people or not (ask.sessions or ask.projects):
            continue
        for n in everything:
            if (
                who_wrote(n) in people
                and who_wrote(n) != pid
                and pid not in n.mentions
                and n.id != ask.id
                and _when_written(n) > ask.created_at
                and _same_place(n, ask)
            ):
                out.setdefault(n.id, ask.id)
    return out


def inbox_for(store: Any, cs: Any, pid: str) -> dict:
    """What names this person, newest first, in three piles, and what they
    wrote. New: not yet opened. Open: opened, and nothing written by them on
    that session or project since. Done: they wrote there after the ask. An
    ask with no place to answer is done once opened. Mine: their own lines,
    newest first, each with where it was written and, for an ask, who has
    answered it so far."""
    nb = cs.notebook
    asks = nb.query_notes(person=pid)
    seen = read_seen(cs, pid)
    # ponytail: one scan of every note serves "done" and "mine"; a `by` index when it grows.
    everything = nb.query_notes()
    mine = [n for n in everything if n.by == pid]

    def answered(a: Note) -> bool:
        if a.sessions or a.projects:
            return _wrote_after(mine, pid, a)
        return a.id in seen

    # One list in time order, newest first, each ask saying whether it has
    # been opened and whether it has been answered; the piles are the same
    # facts sorted, kept for callers that read them. A reply in a
    # conversation this person is part of sits among the asks, saying which
    # ask it follows.
    replies = _replies(everything, pid)
    asks = sorted(
        asks + [n for n in everything if n.id in replies],
        key=lambda n: n.created_at,
        reverse=True,
    )
    ordered: list[dict] = []
    piles: dict[str, list[dict]] = {"new": [], "open": [], "done": []}
    for a in asks:
        done = answered(a)
        item = _item(store, cs, a)
        if a.id in replies:
            item["reply_to"] = replies[a.id]
        item["seen"] = a.id in seen
        item["answered"] = done
        ordered.append(item)
        pile = "done" if done else ("open" if a.id in seen else "new")
        piles[pile].append(item)
    piles["done"] = piles["done"][:20]
    written = []
    for n in mine[:30]:
        item = _item(store, cs, n)
        if n.mentions:
            item["answered_by"] = [p for p in n.mentions if _wrote_after(everything, p, n)]
        written.append(item)
    return {"me": pid, "asks": ordered[:50], **piles, "mine": written}


def create_router(server: Any) -> APIRouter:
    router = APIRouter()

    def _stores():
        cs = getattr(server, "context_store", None)
        bridge = getattr(server, "agent_bridge", None)
        agent = getattr(bridge, "agent", None) if bridge is not None else None
        store = (getattr(agent, "store", None) if agent is not None else None) or getattr(
            server, "gently_store", None
        )
        return store, cs

    @router.get("/api/inbox")
    async def get_inbox(request: Request):
        """The asks that name whoever this request is."""
        store, cs = _stores()
        me = current_username(request)
        if cs is None or not me:
            return {"me": me, "asks": [], "new": [], "open": [], "done": [], "mine": []}
        # Off the event loop: it reads every note, and the page polls it.
        return await asyncio.to_thread(inbox_for, store, cs, me)

    @router.post("/api/inbox/seen")
    async def post_seen(request: Request, body: dict = Body(default={})):  # noqa: B008
        """This person opened these asks. Returns the inbox as it now stands."""
        store, cs = _stores()
        me = current_username(request)
        if cs is None or not me:
            return {"me": me, "asks": [], "new": [], "open": [], "done": [], "mine": []}
        mark_seen(cs, me, [str(x) for x in (body.get("ids") or [])])
        return await asyncio.to_thread(inbox_for, store, cs, me)

    return router
