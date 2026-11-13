"""What the Sessions list says of each session, kept between requests and
between runs of the app.

The list asked every session's folder the same questions on every load: which
embryos, how many projections each, the checkpoint, the snapshots, the
references. On this rig that is 383 sessions, of which 310 hold no embryo, and
the answers for a session that has ended do not change. Measured against a
copy of its session metadata the list took 0.4 s a load and 0.7 s the first
time, and the sizes took another 4 s in sixteen requests, again after every
restart, because what a folder weighs was remembered only in memory.

So what was read is kept, in one small file beside the session index, and a
session is read again only when it has changed. Changed means its
``session.yaml`` or its ``timelapse.yaml`` is not the file that was read: a
rename, a filing, a resume and every round of a run rewrite one or the other.
Two ``stat`` calls a session, where there were a dozen opens and scans.

"Not the file that was read" is the file's time, its size and which file it
is. The store writes a YAML file whole and renames it into place, so every
write is a new file; time and size alone are the same for two writes of the
same length inside one tick of the clock, which is how the store's own read
memo came to answer with the file before last.

The live session is never answered from here: it is the one folder that
changes between its checkpoints (a test volume, an embryo registered), and it
is one session.

This is a cache. It holds nothing that is not in the session folders, it can
be deleted at any time, and a file it cannot read is an empty cache.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Bumped when what a kept row means changes: an older file is then ignored.
VERSION = 1

# The two files whose rewriting marks a session as changed.
_WATCHED = ("session.yaml", "timelapse.yaml")


def fingerprint(folder: Path | None) -> list | None:
    """What identifies the state of a session folder that a row was read
    from: the time, the size and the identity of its ``session.yaml`` and of
    its ``timelapse.yaml`` (None where there is none). None for a folder with
    no ``session.yaml``, which is not a session."""
    if folder is None:
        return None
    out: list = []
    for name in _WATCHED:
        try:
            st = os.stat(os.path.join(folder, name))
            out.append([st.st_mtime_ns, st.st_size, st.st_ino])
        except OSError:
            out.append(None)
    return out if out[0] is not None else None


class SessionListCache:
    """Rows kept by session id, each with the fingerprint it was read under."""

    def __init__(self, path: Path | None):
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._dirty = False

    def _load(self) -> None:
        # Under the lock.
        if self._loaded:
            return
        self._loaded = True
        if self._path is None:
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                doc = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            logger.info("session list cache at %s could not be read; starting empty", self._path)
            return
        if isinstance(doc, dict) and doc.get("version") == VERSION:
            rows = doc.get("sessions")
            if isinstance(rows, dict):
                self._rows = {k: v for k, v in rows.items() if isinstance(v, dict)}

    def get(self, session_id: str, fp: list | None) -> dict | None:
        """The kept row, if it was read from the folder as it is now."""
        if fp is None:
            return None
        with self._lock:
            self._load()
            kept = self._rows.get(session_id)
            if kept is None or kept.get("fp") != fp:
                return None
            return kept

    def put(self, session_id: str, fp: list | None, row: dict[str, Any]) -> dict[str, Any]:
        """Keep a row as read under ``fp``. Returns the row as kept."""
        kept = dict(row, fp=fp)
        if fp is None:
            return kept
        with self._lock:
            self._load()
            self._rows[session_id] = kept
            self._dirty = True
        return kept

    def note(self, session_id: str, fp: list | None, **fields: Any) -> None:
        """Add to a kept row what was learnt later (what the folder weighs,
        what its event capture holds), if the row is still of this folder."""
        if fp is None:
            return
        with self._lock:
            self._load()
            kept = self._rows.get(session_id)
            if kept is None or kept.get("fp") != fp:
                return
            for key, value in fields.items():
                if kept.get(key) != value:
                    kept[key] = value
                    self._dirty = True

    def forget(self, session_id: str, *fields: str) -> None:
        """Drop a kept row, or only the named fields of it: a size that an
        export has just made wrong, without the rest being read again."""
        with self._lock:
            self._load()
            kept = self._rows.get(session_id)
            if kept is None:
                return
            if not fields:
                del self._rows[session_id]
                self._dirty = True
                return
            for key in fields:
                if key in kept:
                    del kept[key]
                    self._dirty = True

    def keep_only(self, session_ids) -> None:
        """Forget every session that is no longer in the index."""
        wanted = set(session_ids)
        with self._lock:
            self._load()
            gone = [k for k in self._rows if k not in wanted]
            for k in gone:
                del self._rows[k]
            if gone:
                self._dirty = True

    def save(self) -> None:
        """Write the file if anything changed. Never raises: a cache that
        cannot be written is a slower list, not a failed one."""
        with self._lock:
            if not self._dirty or self._path is None:
                return
            doc = {"version": VERSION, "sessions": self._rows}
            try:
                payload = json.dumps(doc, separators=(",", ":"), default=str)
            except (TypeError, ValueError):
                logger.debug("session list cache could not be serialised", exc_info=True)
                return
            self._dirty = False
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp, self._path)
        except OSError:
            logger.debug("session list cache could not be written", exc_info=True)
            with self._lock:
                self._dirty = True
