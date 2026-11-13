"""The Sessions list keeps what it read of a session, and reads it again only
when the session has changed.

"Need to go over the sessions tab ... also made super efficient in loading
times."

The list asked every session's folder the same questions on every load: which
embryos, how many projections each, the checkpoint, the snapshots, the
references. On this rig that is 383 sessions, 310 of them with no embryo, and
a session that has ended does not change. Against a copy of the rig's session
metadata the list took 0.4 s a load (0.7 s the first), and the sizes another
4 s in sixteen requests after every restart, because what a folder weighs was
remembered only in memory.

What was read is kept in ``sessions/_list_cache.json``. A session is read
again when its ``session.yaml`` or ``timelapse.yaml`` is not the file that was
read. The live session is always read. Measured after: about 70 ms a load,
and the sizes come with the list.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core import session_list_cache
from gently.core.file_store import FileStore
from gently.core.session_list_cache import SessionListCache, fingerprint
from gently.ui.web import auth
from gently.ui.web.routes import sessions as routes


@pytest.fixture(autouse=True)
def _fresh_caches():
    # One cache a storage root, for the life of the process: a test's root is
    # its own, but the size memory is keyed by path and tmp paths can recur.
    routes._LIST_CACHES.clear()
    routes._SIZE_CACHE.clear()
    yield
    routes._LIST_CACHES.clear()
    routes._SIZE_CACHE.clear()


@pytest.fixture
def store(tmp_path):
    fs = FileStore(root=tmp_path)
    for sid, name in (("s1", "first"), ("s2", "second"), ("s3", "third")):
        fs.create_session(sid, name=name)
        time.sleep(0.01)  # last_active orders the list
    fs.register_embryo("s2", "embryo_1", position_coarse={"x": 1.0, "y": 2.0}, role="test")
    return fs


def _client(store, active=None):
    server = MagicMock()
    server.agent_bridge.agent.store = store
    server.agent_bridge.agent.session_id = active
    server.context_store = None
    server.gently_store = store
    app = FastAPI()
    app.include_router(routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def _rows(client, query=""):
    r = client.get("/api/sessions" + query)
    assert r.status_code == 200
    return {row["session_id"]: row for row in r.json()["sessions"]}


def _counting(monkeypatch, obj, name):
    calls = []
    real = getattr(obj, name)

    def counted(*a, **k):
        calls.append(a)
        return real(*a, **k)

    monkeypatch.setattr(obj, name, counted)
    return calls


# ── what marks a session as changed ──────────────────────────────────────


def test_a_folder_with_no_session_yaml_is_not_a_session(tmp_path):
    assert fingerprint(tmp_path) is None
    assert fingerprint(None) is None


def test_the_fingerprint_changes_when_either_file_is_rewritten(store):
    folder = store._session_dir("s1")
    before = fingerprint(folder)
    assert before is not None and before[1] is None  # no checkpoint yet
    store.update_session("s1", name="renamed")
    renamed = fingerprint(folder)
    assert renamed != before
    (Path(folder) / "timelapse.yaml").write_text("status: idle\n", encoding="utf-8")
    assert fingerprint(folder) != renamed
    # And it is the same for a folder nobody has touched.
    assert fingerprint(folder) == fingerprint(folder)


def test_a_rewrite_that_time_and_size_do_not_show_is_still_seen(store):
    # Two writes of the same length inside one tick of the clock have the
    # same time and the same size; the store's own read memo answered with
    # the file before last that way (tests/
    # test_a_rewritten_yaml_is_read_as_written.py). The store writes a file
    # whole and renames it into place, so every write is a new file, and the
    # fingerprint goes by which file it is as well.
    import os

    from gently.core.file_store import _read_yaml, _write_yaml

    folder = store._session_dir("s1")
    yaml_path = Path(folder) / "session.yaml"
    was = os.stat(yaml_path)
    before = fingerprint(folder)
    data = _read_yaml(yaml_path)
    data["name"] = "fjrst"  # the same length as "first"
    _write_yaml(yaml_path, data)
    os.utime(yaml_path, ns=(was.st_atime_ns, was.st_mtime_ns))
    now = os.stat(yaml_path)
    assert (now.st_mtime_ns, now.st_size) == (was.st_mtime_ns, was.st_size)
    assert fingerprint(folder) != before


# ── the cache itself ─────────────────────────────────────────────────────


def test_a_row_is_given_back_only_for_the_folder_it_was_read_from(tmp_path):
    cache = SessionListCache(tmp_path / "c.json")
    cache.put("s1", [[1, 2], None], {"held": {"embryo_count": 3}})
    assert cache.get("s1", [[1, 2], None])["held"] == {"embryo_count": 3}
    assert cache.get("s1", [[9, 2], None]) is None
    assert cache.get("s1", None) is None
    assert cache.get("nobody", [[1, 2], None]) is None


def test_it_is_still_there_after_a_restart(tmp_path):
    path = tmp_path / "c.json"
    first = SessionListCache(path)
    first.put("s1", [[1, 2], None], {"held": None, "bf_frames": 4})
    first.save()
    assert path.is_file()
    again = SessionListCache(path)
    assert again.get("s1", [[1, 2], None])["bf_frames"] == 4


def test_a_file_it_cannot_read_is_an_empty_cache(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{ not json", encoding="utf-8")
    assert SessionListCache(path).get("s1", [[1, 2], None]) is None
    # Written by a version that meant something else by a row: ignored.
    path.write_text(json.dumps({"version": -1, "sessions": {"s1": {"fp": [[1, 2], None]}}}))
    assert SessionListCache(path).get("s1", [[1, 2], None]) is None
    assert session_list_cache.VERSION != -1


def test_what_is_learnt_later_is_added_to_the_row_it_is_about(tmp_path):
    cache = SessionListCache(tmp_path / "c.json")
    cache.put("s1", [[1, 2], None], {"held": None})
    cache.note("s1", [[1, 2], None], bytes=1234)
    assert cache.get("s1", [[1, 2], None])["bytes"] == 1234
    # Not to a row read from a folder that has since changed.
    cache.note("s1", [[7, 7], None], bytes=9)
    assert cache.get("s1", [[1, 2], None])["bytes"] == 1234
    cache.forget("s1", "bytes")
    assert "bytes" not in cache.get("s1", [[1, 2], None])
    cache.forget("s1")
    assert cache.get("s1", [[1, 2], None]) is None


def test_a_session_gone_from_the_index_is_forgotten(tmp_path):
    cache = SessionListCache(tmp_path / "c.json")
    cache.put("s1", [[1, 2], None], {})
    cache.put("s2", [[1, 2], None], {})
    cache.keep_only(["s2"])
    assert cache.get("s1", [[1, 2], None]) is None
    assert cache.get("s2", [[1, 2], None]) is not None


def test_a_cache_that_cannot_be_written_is_a_slower_list_not_a_failed_one(tmp_path):
    cache = SessionListCache(tmp_path / "no" / "such" / "folder" / "c.json")
    cache.put("s1", [[1, 2], None], {})
    cache.save()  # does not raise
    assert cache.get("s1", [[1, 2], None]) is not None


# ── the list ─────────────────────────────────────────────────────────────


def test_the_list_says_the_same_thing_the_first_time_and_after(store):
    client = _client(store)
    first = _rows(client)
    again = _rows(client)
    assert first == again
    assert set(first) == {"s1", "s2", "s3"}
    assert first["s2"]["embryo_count"] == 1 and first["s1"]["embryo_count"] == 0
    assert first["s1"]["name"] == "first"
    # Newest first, as it was.
    order = [r["session_id"] for r in client.get("/api/sessions").json()["sessions"]]
    assert order == ["s3", "s2", "s1"]


def test_a_session_that_has_not_changed_is_not_read_again(store, monkeypatch):
    client = _client(store)
    _rows(client)
    reads = _counting(monkeypatch, store, "list_embryo_ids")
    yamls = _counting(monkeypatch, store, "get_session")
    _rows(client)
    assert reads == [] and yamls == []


def test_it_is_kept_in_a_file_beside_the_index_and_outlives_the_process(store, monkeypatch):
    _rows(_client(store))
    kept = Path(store.root) / "sessions" / "_list_cache.json"
    assert kept.is_file()
    doc = json.loads(kept.read_text(encoding="utf-8"))
    assert set(doc["sessions"]) == {"s1", "s2", "s3"}
    # A new process: nothing in memory.
    routes._LIST_CACHES.clear()
    reads = _counting(monkeypatch, store, "list_embryo_ids")
    rows = _rows(_client(store))
    assert reads == []
    assert rows["s2"]["embryo_count"] == 1


def test_a_renamed_session_is_read_again_and_says_its_new_name(store, monkeypatch):
    client = _client(store)
    _rows(client)
    store.update_session("s1", name="renamed")
    reads = _counting(monkeypatch, store, "list_embryo_ids")
    rows = _rows(client)
    assert rows["s1"]["name"] == "renamed"
    # Only the one that changed.
    assert [a[0] for a in reads] == ["s1"]


def test_the_live_session_is_always_read(store, monkeypatch):
    client = _client(store, active="s2")
    _rows(client)
    reads = _counting(monkeypatch, store, "list_embryo_ids")
    # An embryo registered between two loads, with no checkpoint written:
    # nothing but reading the folder would know.
    store.register_embryo("s2", "embryo_2", position_coarse={"x": 3.0, "y": 4.0}, role="test")
    rows = _rows(client)
    assert rows["s2"]["embryo_count"] == 2 and rows["s2"]["active"] is True
    assert [a[0] for a in reads] == ["s2"]
    # And it is not kept as if it had ended.
    kept = json.loads(
        (Path(store.root) / "sessions" / "_list_cache.json").read_text(encoding="utf-8")
    )
    assert "s2" not in kept["sessions"]


def test_the_project_and_unfiled_views_are_the_same_rows_narrowed(store):
    store.set_session_project("s1", "proj_a")
    client = _client(store)
    assert set(_rows(client, "?project_id=proj_a")) == {"s1"}
    assert set(_rows(client, "?unfiled=1")) == {"s2", "s3"}
    assert _rows(client)["s1"]["project_id"] == "proj_a"


def test_the_event_capture_is_read_to_its_end_once(store, monkeypatch):
    folder = Path(store._session_dir("s1"))
    (folder / "events.jsonl").write_text(
        json.dumps({"event_type": "ACQUISITION_FAILED", "data": {}}) + "\n", encoding="utf-8"
    )
    client = _client(store)
    counted = _counting(monkeypatch, routes, "signal_counts")
    first = _rows(client, "?unfiled=1")
    assert first["s1"]["errors"] == 1
    n = len(counted)
    assert n == 3
    again = _rows(client, "?unfiled=1")
    assert again["s1"]["errors"] == 1
    assert len(counted) == n


def test_a_store_that_is_not_one_on_disk_is_read_the_long_way():
    # A stand-in with no index: nothing is kept, and it still answers.
    store = MagicMock()
    store.list_sessions.return_value = [
        {"session_id": "a", "name": "A", "created_at": "", "last_active": "", "projects": []}
    ]
    store.list_embryo_ids.return_value = []
    assert routes.list_cache_for(store) is None
    rows = _rows(_client(store))
    assert set(rows) == {"a"} and rows["a"]["name"] == "A"


# ── what a session weighs ────────────────────────────────────────────────


def test_a_size_is_counted_once_and_comes_with_the_list_from_then_on(store, monkeypatch):
    client = _client(store)
    assert _rows(client)["s1"]["bytes"] is None
    sizes = client.get("/api/sessions/sizes?ids=s1,s2,s3").json()["sizes"]
    assert all(isinstance(v, int) and v > 0 for v in sizes.values())
    assert _rows(client)["s1"]["bytes"] == sizes["s1"]
    # After a restart too, and without walking the folders again.
    routes._LIST_CACHES.clear()
    routes._SIZE_CACHE.clear()
    walks = _counting(monkeypatch, routes, "folder_bytes")
    client = _client(store)
    assert _rows(client)["s2"]["bytes"] == sizes["s2"]
    again = client.get("/api/sessions/sizes?ids=s1,s2,s3").json()["sizes"]
    assert again == sizes
    assert walks == []


def test_the_live_sessions_size_is_counted_afresh(store, monkeypatch):
    client = _client(store, active="s2")
    _rows(client)
    client.get("/api/sessions/sizes?ids=s2")
    walks = _counting(monkeypatch, routes, "folder_bytes")
    client.get("/api/sessions/sizes?ids=s2")
    assert len(walks) == 1


def test_a_size_is_forgotten_when_something_is_written_into_the_folder(store):
    client = _client(store)
    _rows(client)
    client.get("/api/sessions/sizes?ids=s1")
    cache = routes.list_cache_for(store)
    folder = store._session_dir("s1")
    assert cache.get("s1", fingerprint(folder)).get("bytes") is not None
    # What an export or a movie does when it finishes.
    cache.forget("s1", "bytes")
    assert cache.get("s1", fingerprint(folder)).get("bytes") is None


# ── the launch gate asks the same question ───────────────────────────────


def test_the_launch_gate_is_answered_from_what_the_list_kept(store, monkeypatch):
    client = _client(store)
    first = client.get("/api/sessions/resumable").json()["sessions"]
    assert [s["session_id"] for s in first] == ["s2"]  # the one with an embryo
    reads = _counting(monkeypatch, store, "list_embryo_ids")
    again = client.get("/api/sessions/resumable").json()["sessions"]
    assert again == first
    assert reads == []
