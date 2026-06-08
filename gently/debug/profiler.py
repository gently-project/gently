"""Lightweight JSONL profiler spans for debug exports."""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)


def resolve_profile_path(context: Optional[Mapping[str, Any]]) -> Optional[Path]:
    """Resolve where runtime profile spans should be written.

    The explicit ``GENTLY_PROFILE_PATH`` env var wins. Otherwise, when an agent
    with a FileStore session is available, spans go beside the session artifacts
    as ``profile_spans.jsonl``.
    """
    explicit = os.environ.get("GENTLY_PROFILE_PATH", "").strip()
    if explicit:
        return Path(explicit)

    if not isinstance(context, Mapping):
        return None
    agent = context.get("agent")
    if agent is None:
        return None

    direct = getattr(agent, "profile_path", None)
    if direct:
        return Path(direct)

    session_id = getattr(agent, "session_id", None)
    store = getattr(agent, "store", None)
    if session_id and store is not None and hasattr(store, "_session_dir"):
        try:
            session_dir = store._session_dir(session_id)
        except Exception:
            session_dir = None
        if session_dir is not None:
            return Path(session_dir) / "profile_spans.jsonl"

    return None


def record_profile_span(
    context: Optional[Mapping[str, Any]],
    *,
    component: str,
    operation: str,
    duration_ms: float,
    status: str,
    metadata: Optional[Mapping[str, Any]] = None,
) -> None:
    """Append one profile span, best-effort and non-fatal."""
    path = resolve_profile_path(context)
    if path is None:
        return

    record = {
        "timestamp": datetime.now().isoformat(timespec="milliseconds"),
        "hostname": socket.gethostname(),
        "component": component,
        "operation": operation,
        "duration_ms": round(float(duration_ms), 3),
        "status": status,
    }
    if metadata:
        record.update(dict(metadata))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except Exception as exc:
        logger.debug("failed to write profile span to %s: %s", path, exc)
