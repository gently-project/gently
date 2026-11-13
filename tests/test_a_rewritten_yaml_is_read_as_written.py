"""A YAML file the store has just rewritten is read as it was written.

The store remembers a parsed YAML file by its time and size, so a file that
has not changed is not opened and parsed again. A file rewritten at the same
size inside one tick of the filesystem's clock has the same time and the same
size, and was answered from memory: the file before last.

It was found as a test that failed about one run in six on the rig's PC
(tests/test_membership.py): a session moved from one project to another, whose
ids are the same length, read back as still in the first. On the rig that is a
session filed under the wrong project until something else rewrites its
session.yaml.

The store is the one that rewrote it, so it forgets what it had read.
"""

from __future__ import annotations

import os

from gently.core.file_store import FileStore, _read_yaml, _write_yaml


def _same_tick(path, before) -> None:
    """Put the file's time back to what it was: two writes inside one tick of
    the clock, made to happen every time instead of one time in six."""
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_a_file_rewritten_at_the_same_size_in_the_same_tick_is_read_as_written(tmp_path):
    path = tmp_path / "session.yaml"
    _write_yaml(path, {"project_id": "2290cb01"})
    before = os.stat(path)
    assert _read_yaml(path) == {"project_id": "2290cb01"}

    _write_yaml(path, {"project_id": "353f5311"})
    _same_tick(path, before)
    after = os.stat(path)
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)

    assert _read_yaml(path) == {"project_id": "353f5311"}


def test_a_file_that_has_not_changed_is_still_not_parsed_again(tmp_path, monkeypatch):
    # What the memo is for, kept: the Sessions list read every session.yaml
    # twice a call.
    import yaml

    path = tmp_path / "a.yaml"
    _write_yaml(path, {"a": 1})
    assert _read_yaml(path) == {"a": 1}
    parses = []
    real = yaml.load
    monkeypatch.setattr(yaml, "load", lambda *a, **k: parses.append(1) or real(*a, **k))
    assert _read_yaml(path) == {"a": 1}
    assert _read_yaml(path) == {"a": 1}
    assert parses == []


def test_what_a_caller_does_to_a_document_stays_theirs(tmp_path):
    path = tmp_path / "a.yaml"
    _write_yaml(path, {"links": [1]})
    got = _read_yaml(path)
    got["links"].append(2)
    assert _read_yaml(path) == {"links": [1]}


def test_a_session_moved_between_projects_reads_back_as_moved(tmp_path):
    # The store's own path through it, in the same tick.
    store = FileStore(root=tmp_path)
    store.create_session("s1", name="x", project_id="2290cb01")
    yaml_path = store._session_dir("s1") / "session.yaml"
    assert store.get_session("s1")["project_id"] == "2290cb01"
    before = os.stat(yaml_path)
    data = _read_yaml(yaml_path)
    data["project_id"] = "353f5311"
    _write_yaml(yaml_path, data)
    _same_tick(yaml_path, before)
    assert store.get_session("s1")["project_id"] == "353f5311"
