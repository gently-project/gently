"""Persistent notes from the Gently agent to a coding agent."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


@dataclass(frozen=True)
class CodingAgentNote:
    """A structured note intended for a future coding-agent pass."""

    note_id: str
    timestamp: str
    message: str
    session_id: Optional[str] = None
    category: str = "feedback"
    severity: str = "info"
    source: str = "gently_agent"
    context: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CodingAgentNote":
        return cls(
            note_id=str(data.get("note_id", "")),
            timestamp=str(data.get("timestamp", "")),
            message=str(data.get("message", "")),
            session_id=data.get("session_id"),
            category=str(data.get("category", "feedback")),
            severity=str(data.get("severity", "info")),
            source=str(data.get("source", "gently_agent")),
            context=data.get("context") or {},
        )


class CodingNotesStore:
    """Append-only JSONL store for coding-agent notes."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def for_agent(cls, agent) -> "CodingNotesStore":
        """Resolve the best notes path for an agent-like object."""
        session_id = getattr(agent, "session_id", None)
        store = getattr(agent, "store", None)
        if store is not None and session_id and hasattr(store, "_session_dir"):
            session_dir = store._session_dir(session_id)
            if session_dir is not None:
                return cls(session_dir / "coding_agent_notes.jsonl")

        storage_path = Path(getattr(agent, "storage_path", "."))
        return cls(storage_path / "coding_agent_notes.jsonl")

    def append_note(
        self,
        message: str,
        *,
        session_id: Optional[str] = None,
        category: str = "feedback",
        severity: str = "info",
        source: str = "gently_agent",
        context: Optional[Mapping[str, Any]] = None,
    ) -> CodingAgentNote:
        """Append a note and return the stored record."""
        cleaned = message.strip()
        if not cleaned:
            raise ValueError("note message cannot be empty")

        note = CodingAgentNote(
            note_id=uuid.uuid4().hex[:12],
            timestamp=datetime.now().isoformat(),
            message=cleaned,
            session_id=session_id,
            category=category.strip().lower() or "feedback",
            severity=severity.strip().lower() or "info",
            source=source,
            context=dict(context or {}),
        )

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(note.to_dict(), default=str) + "\n")
        return note

    def list_notes(
        self,
        *,
        limit: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[CodingAgentNote]:
        """Read notes from newest to oldest."""
        if not self.path.exists():
            return []

        wanted_category = category.strip().lower() if category else None
        notes: List[CodingAgentNote] = []
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    note = CodingAgentNote.from_dict(json.loads(raw))
                except json.JSONDecodeError:
                    continue
                if wanted_category and note.category != wanted_category:
                    continue
                notes.append(note)

        notes.reverse()
        if limit is not None:
            return notes[:max(0, limit)]
        return notes
