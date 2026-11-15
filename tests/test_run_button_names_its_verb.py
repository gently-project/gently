"""`Start` must say what it will do.

`startRun` branched on `_mode` into four different verbs, and the button said
"Start" for all four. Two of the four were never kinds of run, and are no
longer modes of Start: a test volume is a button beside the pictures that
names its embryo, and handing the embryos to the agent is a button under
Start. What is left is the form's plan (`adaptive`) and a saved tactic run as
it is (`library`).

Two invariants worth pinning, because both rot silently:

1. Every mode has a verb. A mode `setMode` can set but `RUN_VERB` does not
   name falls back to "Start" and quietly reintroduces the ambiguity.
2. `subjectIds()` keeps no fallback. The old `subs.length ? subs : all` could
   only ever fire when EVERY embryo was marked `calibration` — an embryo with
   no role, or 'test', or 'unassigned' already passes the filter. So it fired
   exactly when the operator had said "these are all references" and answered
   by imaging all of them as subjects.

ponytail: source assertions, because operate.js is an IIFE with no export
surface and CI runs no JavaScript. They check the shape, not the behaviour.
"""

from __future__ import annotations

import re
from pathlib import Path

OPERATE = (
    Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js" / "operate.js"
)


def _src() -> str:
    return OPERATE.read_text(encoding="utf-8")


def test_every_run_mode_has_a_verb() -> None:
    src = _src()

    block = src[src.index("const RUN_VERB = {") : src.index("function renderRunButton")]
    verbs = set(re.findall(r"(\w+):\s*'", block))

    assert "_mode = m === 'library' ? 'library' : 'adaptive';" in src, (
        "setMode's modes changed — update this test alongside it"
    )
    modes = {"adaptive", "library"}

    assert modes <= verbs, (
        f"modes with no verb in RUN_VERB: {sorted(modes - verbs)} — the button "
        "falls back to 'Start' for those and the ambiguity is back"
    )


def test_a_test_volume_does_not_claim_to_start_anything() -> None:
    """It acquires one volume and finishes. Its button must not imply a run,
    and must say which embryo."""
    src = _src()
    block = src[src.index("const RUN_VERB = {") : src.index("function renderRunButton")]
    assert "single:" not in block and "agent:" not in block
    name = src[src.index("    function renderSingle() {") :]
    name = name[: name.index("\n    }")]
    label = re.search(r"b\.textContent = emb \? `([^`]+)` : '([^']+)';", name)
    assert label, "the test volume's button lost its name"
    for said in label.groups():
        assert "start" not in said.lower(), f"{said!r} reads as starting an experiment"
    assert "${labelFor(emb)}" in label.group(1), "it does not say which embryo"


def test_subject_ids_keeps_no_fallback() -> None:
    src = _src()
    body = src[src.index("function subjectIds()") :]
    body = body[: body.index("}")]
    assert "_embryos.map" not in body, (
        "subjectIds() has a fallback again — it can only fire when every embryo "
        "is a reference, and it answers by imaging all of them as subjects"
    )


def test_a_reference_only_roster_is_refused_rather_than_imaged() -> None:
    src = _src()
    assert "function haveSubjects()" in src
    assert src.count("haveSubjects()") >= 3, (
        "haveSubjects is defined but not guarding both roster-driven run modes"
    )
    # "no embryos" and "no subjects among your embryos" need different fixes,
    # so the guard must distinguish them rather than emitting one message.
    guard = src[src.index("function haveSubjects()") :]
    guard = guard[: guard.index("\n    }")]
    assert "No embryos registered" in guard
    assert "marked as a reference" in guard
