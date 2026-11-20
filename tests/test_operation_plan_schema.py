"""The operation plan's tactic schema: what every writer's tactics are normalised to.

Kinds, states, scopes and phases arrive in many spellings (an agent's, a saved
tactic's, a plan item's outline); `_validate_tactics` turns them into the one
shape Operate's run spine and the tactic executor read.
"""

# ---------------------------------------------------------------------------
# Normalization tests (Fix 2)
# ---------------------------------------------------------------------------


def test_normalize_kind_synonyms():
    """Kind synonyms are mapped to canonical values before validation."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    cases = [
        ("monitor", "reactive_monitor"),
        ("reactive", "reactive_monitor"),
        ("timelapse", "standing_timelapse"),
        ("standing", "standing_timelapse"),
        ("protocol", "scripted_protocol"),
        ("scripted", "scripted_protocol"),
        ("burst", "exclusive_burst"),
        ("reference", "standing_timelapse"),
    ]
    for raw_kind, expected in cases:
        tactics = [{"id": "t1", "name": "T", "kind": raw_kind, "state": "planned"}]
        result = _validate_tactics(tactics)
        assert result[0]["kind"] == expected, f"kind '{raw_kind}' should map to '{expected}'"


def test_normalize_kind_unknown_to_custom():
    """An unrecognised kind that is not a synonym is clamped to 'custom'."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [{"id": "t1", "name": "T", "kind": "future_kind_v99", "state": "planned"}]
    result = _validate_tactics(tactics)
    assert result[0]["kind"] == "custom"


def test_normalize_scope_bare_list():
    """A bare list scope is converted to {mode:'embryos', embryo_ids:[...]}."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [
        {
            "id": "t1",
            "name": "T",
            "kind": "standing_timelapse",
            "state": "planned",
            "scope": ["E01", "E02"],
        }
    ]
    result = _validate_tactics(tactics)
    assert result[0]["scope"] == {"mode": "embryos", "embryo_ids": ["E01", "E02"]}


def test_normalize_scope_global_string():
    """The string 'global' scope is converted to {mode:'global'}."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [
        {
            "id": "t1",
            "name": "T",
            "kind": "standing_timelapse",
            "state": "planned",
            "scope": "global",
        }
    ]
    result = _validate_tactics(tactics)
    assert result[0]["scope"] == {"mode": "global"}


def test_normalize_scope_dict_missing_mode_with_embryo_ids():
    """A scope dict with embryo_ids but no mode gets mode:'embryos' injected."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [
        {
            "id": "t1",
            "name": "T",
            "kind": "standing_timelapse",
            "state": "planned",
            "scope": {"embryo_ids": ["E01"]},
        }
    ]
    result = _validate_tactics(tactics)
    assert result[0]["scope"]["mode"] == "embryos"
    assert result[0]["scope"]["embryo_ids"] == ["E01"]


def test_normalize_scope_dict_missing_mode_with_role():
    """A scope dict with role but no mode gets mode:'role' injected."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [
        {
            "id": "t1",
            "name": "T",
            "kind": "standing_timelapse",
            "state": "planned",
            "scope": {"role": "test"},
        }
    ]
    result = _validate_tactics(tactics)
    assert result[0]["scope"]["mode"] == "role"
    assert result[0]["scope"]["role"] == "test"


def test_normalize_scope_well_formed_dict_unchanged():
    """A correctly formed scope dict passes through unchanged."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    scope = {"mode": "embryos", "embryo_ids": ["E01", "E02"]}
    tactics = [
        {
            "id": "t1",
            "name": "T",
            "kind": "standing_timelapse",
            "state": "planned",
            "scope": scope,
        }
    ]
    result = _validate_tactics(tactics)
    assert result[0]["scope"] == scope


def test_normalize_phase_state_pending_to_todo():
    """Phase state 'pending' is normalized to 'todo'."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [
        {
            "id": "t1",
            "name": "T",
            "kind": "scripted_protocol",
            "state": "planned",
            "live": {
                "readouts": [],
                "phases": [
                    {"name": "ramp", "state": "pending", "count": 0, "pips": []},
                    {"name": "hold", "state": "running", "count": 0, "pips": []},
                    {"name": "done_phase", "state": "completed", "count": 3, "pips": []},
                ],
            },
        }
    ]
    result = _validate_tactics(tactics)
    phases = result[0]["live"]["phases"]
    assert phases[0]["state"] == "todo"
    assert phases[1]["state"] == "active"
    assert phases[2]["state"] == "done"


def test_normalize_tactic_state_synonyms():
    """Tactic state synonyms are mapped to canonical values."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    cases = [
        ("in_progress", "active"),
        ("running", "active"),
        ("pending", "planned"),
        ("queued", "planned"),
        ("complete", "done"),
        ("completed", "done"),
    ]
    for raw_state, expected in cases:
        tactics = [{"id": "t1", "name": "T", "kind": "oneshot", "state": "planned"}]
        # Override state directly
        tactics[0]["state"] = raw_state
        result = _validate_tactics(tactics)
        assert result[0]["state"] == expected, f"state '{raw_state}' should map to '{expected}'"


def test_normalize_full_scenario():
    """Combined: kind synonym + bare-list scope + pending phase state + running tactic state."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    tactics = [
        {
            "id": "t1",
            "name": "Temp monitor",
            "kind": "monitor",  # synonym → reactive_monitor
            "state": "in_progress",  # synonym → active
            "scope": ["E01", "E02"],  # bare list → {mode:embryos, embryo_ids:[...]}
            "rationale": "Watch temp",
            "live": {
                "readouts": [{"label": "temp", "value": "25 °C"}],
                "phases": [
                    {"name": "watch", "state": "pending", "count": 0, "pips": []},
                ],
            },
        }
    ]
    result = _validate_tactics(tactics)
    t = result[0]
    assert t["kind"] == "reactive_monitor"
    assert t["state"] == "active"
    assert t["scope"] == {"mode": "embryos", "embryo_ids": ["E01", "E02"]}
    assert t["live"]["phases"][0]["state"] == "todo"
    assert t["live"]["readouts"] == [{"label": "temp", "value": "25 °C"}]
