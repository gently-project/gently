"""
The operation plan's tactic schema, and the one validator every writer of a
session's tactics goes through: the tactic executor appending a run started
from Operate or a saved tactic, and the data routes. The plan is the
session's record of its tactics and their state (FileContextStore), which
Operate's run spine, Stop and Continue read.

The agent once declared the plan itself, with display fields for the
Operations tab's spine (`declare_operation_plan`). The spine is gone, and so
is that tool: a session's tactics come from what is run.
"""

import logging

logger = logging.getLogger(__name__)

# Valid kind / state values per §1 of the spec
_VALID_KINDS = frozenset(
    {
        "standing_timelapse",
        "reactive_monitor",
        "scripted_protocol",
        "exclusive_burst",
        "oneshot",
        "custom",
    }
)
_VALID_STATES = frozenset({"planned", "active", "done", "paused"})

# Synonym maps — normalize model variation to canonical values
_KIND_SYNONYMS: dict[str, str] = {
    "monitor": "reactive_monitor",
    "reactive": "reactive_monitor",
    "timelapse": "standing_timelapse",
    "standing": "standing_timelapse",
    "protocol": "scripted_protocol",
    "scripted": "scripted_protocol",
    "burst": "exclusive_burst",
    "reference": "standing_timelapse",
}

_STATE_SYNONYMS: dict[str, str] = {
    "in_progress": "active",
    "running": "active",
    "pending": "planned",
    "queued": "planned",
    "complete": "done",
    "completed": "done",
}

_PHASE_STATE_SYNONYMS: dict[str, str] = {
    "pending": "todo",
    "queued": "todo",
    "todo": "todo",
    "running": "active",
    "in_progress": "active",
    "active": "active",
    "complete": "done",
    "completed": "done",
    "done": "done",
}


def _normalize_scope(scope: object) -> object:
    """Normalize scope to canonical {mode, ...} object form."""
    if isinstance(scope, list):
        return {"mode": "embryos", "embryo_ids": scope}
    if isinstance(scope, str):
        if scope in ("global", "all"):
            return {"mode": "global"}
        # unknown string — wrap as global fallback
        return {"mode": "global"}
    if isinstance(scope, dict):
        if "mode" not in scope:
            scope = dict(scope)
            if "role" in scope:
                scope["mode"] = "role"
            elif "embryo_ids" in scope:
                scope["mode"] = "embryos"
        return scope
    # unexpected type — pass through unchanged so we don't lose data
    return scope


def _normalize_phases(phases: object) -> object:
    """Normalize phase state values inside a phases list."""
    if not isinstance(phases, list):
        return phases
    result = []
    for phase in phases:
        if isinstance(phase, dict) and "state" in phase:
            raw = phase["state"]
            phase = dict(phase)
            phase["state"] = _PHASE_STATE_SYNONYMS.get(raw, raw)
        result.append(phase)
    return result


def _validate_tactics(tactics: list) -> list[dict]:
    """Validate and normalise a tactics list.

    Each tactic must have id, name, kind, state.
    Kind synonyms are mapped to canonical values; unknown kinds are clamped to
    'custom'.  State synonyms are mapped to canonical values; unknown states
    raise ValueError.  Scope is normalized to {mode, ...} object form.
    Phase states inside live.phases are normalized to todo/active/done.
    """
    validated = []
    for i, t in enumerate(tactics):
        if not isinstance(t, dict):
            raise ValueError(f"Tactic at index {i} must be a dict, got {type(t).__name__}")
        for required_field in ("id", "name", "kind", "state"):
            if not t.get(required_field):
                raise ValueError(f"Tactic at index {i} missing required field '{required_field}'")
        tactic = dict(t)

        # --- normalize kind ---
        kind = tactic["kind"]
        kind = _KIND_SYNONYMS.get(kind, kind)
        if kind not in _VALID_KINDS:
            logger.warning(
                "Tactic '%s' has unknown kind '%s' — clamped to 'custom'",
                tactic.get("id"),
                kind,
            )
            kind = "custom"
        tactic["kind"] = kind

        # --- normalize tactic state ---
        state = tactic["state"]
        state = _STATE_SYNONYMS.get(state, state)
        if state not in _VALID_STATES:
            raise ValueError(
                f"Tactic '{tactic.get('id')}' has invalid state '{state}'. "
                f"Must be one of: {sorted(_VALID_STATES)}"
            )
        tactic["state"] = state

        # --- normalize scope ---
        if "scope" in tactic:
            tactic["scope"] = _normalize_scope(tactic["scope"])

        # --- normalize phase states inside live.phases ---
        live = tactic.get("live")
        if isinstance(live, dict) and "phases" in live:
            live = dict(live)
            live["phases"] = _normalize_phases(live["phases"])
            tactic["live"] = live

        validated.append(tactic)
    return validated
