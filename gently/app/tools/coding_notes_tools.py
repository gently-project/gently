"""Tools for leaving notes to future coding-agent work."""

from typing import Dict, Optional

from gently.harness.coding_notes import CodingNotesStore
from gently.harness.tools.registry import tool, ToolCategory, ToolExample


def _get_notes_store(context: Dict):
    agent = context.get("agent") if context else None
    if not agent:
        return None, None, "Error: No agent context"
    return CodingNotesStore.for_agent(agent), agent, None


@tool(
    name="leave_coding_agent_note",
    description=(
        "Write a persistent note for a future coding agent. Use this when the "
        "user reports a bug, asks for code changes, gives implementation "
        "feedback, or when an internal error reveals something maintainers "
        "should fix later."
    ),
    category=ToolCategory.UTILITY,
    examples=[
        ToolExample(
            "Leave a bug note",
            {
                "message": "User expected move_to_embryo to verify a stored position first.",
                "category": "bug",
                "severity": "warning",
            },
        ),
    ],
)
async def leave_coding_agent_note(
    message: str,
    category: str = "feedback",
    severity: str = "info",
    context_summary: Optional[str] = None,
    context: Dict = None,
) -> str:
    """Persist a coding-agent note."""
    store, agent, err = _get_notes_store(context)
    if err:
        return err

    note_context = {}
    if context_summary:
        note_context["summary"] = context_summary

    try:
        note = store.append_note(
            message,
            session_id=getattr(agent, "session_id", None),
            category=category,
            severity=severity,
            context=note_context,
        )
    except ValueError as exc:
        return f"Error writing coding-agent note: {exc}"

    return f"Saved coding-agent note {note.note_id} to {store.path}"


@tool(
    name="list_coding_agent_notes",
    description=(
        "List recent persistent notes that were left for a future coding agent. "
        "Use this to review outstanding bug reports or implementation feedback."
    ),
    category=ToolCategory.UTILITY,
    examples=[
        ToolExample("Show coding notes", {"limit": 5}),
    ],
)
async def list_coding_agent_notes(
    limit: int = 10,
    category: Optional[str] = None,
    context: Dict = None,
) -> str:
    """List recent coding-agent notes."""
    store, _agent, err = _get_notes_store(context)
    if err:
        return err

    notes = store.list_notes(limit=limit, category=category)
    if not notes:
        return f"No coding-agent notes found at {store.path}"

    lines = [f"Coding-agent notes ({store.path}):"]
    for note in notes:
        lines.append(
            f"- [{note.severity}/{note.category}] {note.timestamp} "
            f"{note.note_id}: {note.message}"
        )
    return "\n".join(lines)
