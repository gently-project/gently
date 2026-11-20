"""Tests for resolve_scope_embryos resolver + role-scoped tactic validation (Task 3, D2).

Resolver lives at gently.app.orchestration.role_scope.resolve_scope_embryos.

Contracts:
- mode='global' → all embryo ids
- mode='embryos' + embryo_ids → exactly those ids
- mode='role' + role='test' → ids of embryos with that role
- mode='role' with unknown role → [] (not an error)
- missing/unknown mode → []
- embryo dicts use 'embryo_id' key (from /api/embryos/positions)

Scope validation in the tactic schema (operation_plan_tools._validate_tactics):
- A tactic with scope.mode='role' and a valid REGISTRY key passes validation.
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_EMBRYOS = [
    {"embryo_id": "e1", "role": "test"},
    {"embryo_id": "e2", "role": "test"},
    {"embryo_id": "e3", "role": "calibration"},
    {"embryo_id": "e4", "role": "lineaging"},
    {"embryo_id": "e5", "role": "unassigned"},
]


# ---------------------------------------------------------------------------
# Resolver tests
# ---------------------------------------------------------------------------


def test_global_scope_returns_all_ids():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "global"}, _EMBRYOS)
    assert set(ids) == {"e1", "e2", "e3", "e4", "e5"}


def test_embryos_scope_returns_explicit_ids():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "embryos", "embryo_ids": ["e1", "e3"]}, _EMBRYOS)
    assert ids == ["e1", "e3"]


def test_role_scope_filters_by_role():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "role", "role": "test"}, _EMBRYOS)
    assert set(ids) == {"e1", "e2"}


def test_role_scope_calibration():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "role", "role": "calibration"}, _EMBRYOS)
    assert ids == ["e3"]


def test_role_scope_lineaging():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "role", "role": "lineaging"}, _EMBRYOS)
    assert ids == ["e4"]


def test_role_scope_unknown_role_returns_empty():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "role", "role": "nonexistent_role"}, _EMBRYOS)
    assert ids == []


def test_unknown_mode_returns_empty():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "burst_only"}, _EMBRYOS)
    assert ids == []


def test_missing_mode_returns_empty():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({}, _EMBRYOS)
    assert ids == []


def test_none_scope_returns_empty():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos(None, _EMBRYOS)
    assert ids == []


def test_empty_embryo_list():
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    ids = resolve_scope_embryos({"mode": "global"}, [])
    assert ids == []


def test_embryo_id_key_used_not_id():
    """Resolver must read 'embryo_id', not 'id'."""
    from gently.app.orchestration.role_scope import resolve_scope_embryos

    # If resolver accidentally uses 'id', this returns []
    embryos = [{"embryo_id": "eX", "role": "test"}]
    ids = resolve_scope_embryos({"mode": "global"}, embryos)
    assert "eX" in ids


# ---------------------------------------------------------------------------
# The tactic schema: a role-scoped tactic passes validation
# ---------------------------------------------------------------------------


def test_role_scoped_tactic_passes_validation():
    """A tactic with scope.mode='role' and a valid role key is kept as it is."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    (tactic,) = _validate_tactics(
        [
            {
                "id": "t-role",
                "name": "Test-embryo timelapse",
                "kind": "standing_timelapse",
                "state": "active",
                "scope": {"mode": "role", "role": "test"},
                "rationale": "Only image the test embryos",
                "structure": {"cadence_s": 120, "per_embryo": []},
            }
        ]
    )
    assert tactic["scope"] == {"mode": "role", "role": "test"}


def test_role_scoped_tactic_all_registry_roles():
    """All four REGISTRY role keys are accepted as valid scope.role values."""
    from gently.app.tools.operation_plan_tools import _validate_tactics

    for role_name in ("test", "calibration", "lineaging", "unassigned"):
        (tactic,) = _validate_tactics(
            [
                {
                    "id": f"t-{role_name}",
                    "name": f"{role_name} monitor",
                    "kind": "standing_timelapse",
                    "state": "planned",
                    "scope": {"mode": "role", "role": role_name},
                    "rationale": f"Target {role_name} embryos",
                }
            ]
        )
        assert tactic["scope"]["role"] == role_name
