"""While a run is going, a verb that would take the instrument from it asks first.

The study (docs/workspace/calibration-and-acquisition.md, "The run owns the
instrument"): "On Scope, while a run is going, the verbs that would take the
instrument from it (Start view, the jog pad, centre on an embryo, the head's
steps, Calibrate) ask before they act."

A timelapse drives the stage to each embryo and takes the cameras on its own
clock. A hand on them mid-run is either undone by the next round or meets the
one in progress, and Scope is one press from Acquisition while a night's run
is going. Nothing said so.

Three things this must not become:

* a gate on which surface is on screen, which operate.js forbids. It reads
  the rig's state, which the shell keeps on <body> for every surface;
* a question per press. One yes holds for a minute, so a correction of
  several jogs is one question;
* a gate on stopping anything. HALT, stopping a live view, Pause and Stop ask
  nothing here.

Checked in a browser with every device request intercepted: five verbs each
asked in its own words and a no sent nothing; one yes let the next three
presses through unasked; a paused run asked nothing. CI drives no browser,
so the wiring is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
OPERATE = (JS / "operate.js").read_text(encoding="utf-8")
PAD = (JS / "panels" / "stage-pad.js").read_text(encoding="utf-8")
SHELL = (JS / "shell.js").read_text(encoding="utf-8")


def _fn(head: str, src: str = OPERATE) -> str:
    body = src[src.index(head) :]
    return body[: body.index("\n    }")]


ASK = _fn("    function mayTakeFromRun(what) {")


def test_it_reads_the_rigs_state_and_not_the_surface_on_screen() -> None:
    assert "if (document.body.dataset.run !== 'running') return true;" in ASK
    # The shell keeps that state for every surface, from the run's own events.
    assert "document.body.dataset.run = status;" in SHELL
    for surface in ("_pane", "_acqView", "_active"):
        assert surface not in ASK, surface


def test_a_paused_run_is_held_on_purpose_and_asks_nothing() -> None:
    # Only 'running' asks: 'paused' and 'idle' go straight through.
    assert ASK.count("dataset.run") == 1 and "'paused'" not in ASK


def test_one_yes_holds_for_a_minute() -> None:
    assert "const HANDS_ON_MS = 60000;" in OPERATE
    assert "if (Date.now() < _handsOnUntil) return true;" in ASK
    assert "if (ok) _handsOnUntil = Date.now() + HANDS_ON_MS;" in ASK
    assert ASK.index("dataset.run") < ASK.index("_handsOnUntil") < ASK.index("window.confirm(")


def test_it_says_what_is_being_taken_and_what_to_do_instead() -> None:
    assert "`A run is going. ${what} takes the instrument from it.`" in ASK
    assert "Pause the run first if this is more than a nudge." in ASK


def test_every_move_of_the_stage_asks() -> None:
    """Centring on an embryo and going to a field come through the one
    chokepoint; the jog pad sends its own moves and is told when to ask."""
    move = _fn("    async function moveStageTo(x, y, said) {")
    assert move.index("if (!mayTakeFromRun('Moving the stage')) return false;") < move.index(
        "'/api/devices/stage/move'"
    )
    assert OPERATE.count("'/api/devices/stage/move'") == 1
    assert "StagePad.setGuard(() => mayTakeFromRun('Moving the stage'));" in OPERATE
    jog = _fn("    async function jog(dx, dy) {", PAD)
    assert jog.index("if (guard && !guard()) return;") < jog.index("'/api/devices/stage/jog'")
    assert "setGuard: fn => { guard = fn; }" in PAD


def test_the_head_asks_and_the_bottom_focus_does_not() -> None:
    nudge = _fn("        async function nudge(delta) {")
    assert nudge.index("if (cfg.takes && !mayTakeFromRun(cfg.takes)) return;") < nudge.index(
        "postJSON(cfg.nudge"
    )
    head = OPERATE[OPERATE.index("    const fd = makeZAxis({") :]
    head = head[: head.index("\n    });")]
    assert "takes: 'Moving the head'," in head
    # The bottom objective's focus is not the run's: refocusing the overview
    # mid-run is a thing an operator does.
    bottom = OPERATE[OPERATE.index("    const bz = makeZAxis({") :]
    bottom = bottom[: bottom.index("\n    });")]
    assert "takes:" not in bottom
    goto = _fn("    async function headTo(um, b) {")
    assert goto.index("if (!mayTakeFromRun('Moving the head')) return;") < goto.index("fdrive/goto")


def test_starting_a_view_asks_and_stopping_one_never_does() -> None:
    cam = _fn("    async function toggleBottomCam() {")
    assert "if (!_bottomOn && !mayTakeFromRun('Starting the bottom camera')) return;" in cam
    spim = _fn("    async function toggleSpim() {")
    assert "if (!_spimOn && !mayTakeFromRun('Starting the light-sheet view')) return;" in spim
    for stop in ("    function stopBottom() {", "    function stopSpim() {"):
        assert "mayTakeFromRun" not in _fn(stop), stop


def test_a_calibration_asks_however_it_is_asked_for() -> None:
    one = _fn("    async function calibrateSelected(opts) {")
    # Before Fit is brought up: a no leaves the page as it was.
    assert one.index("if (!mayTakeFromRun('A calibration')) return;") < one.index("showPane('cal')")
    assert "if (!mayTakeFromRun('Calibrating the rest')) return;" in _fn(
        "    async function calibrateAll() {"
    )
    assert "mayTakeFromRun('Borrowing a fit" in _fn("    async function borrowCalibration() {")


def test_nothing_that_stops_or_holds_the_rig_is_asked_about() -> None:
    callers = re.findall(r"mayTakeFromRun\('([^']+)'", OPERATE)
    assert len(callers) == 8, callers
    for what in callers:
        assert not re.search(r"halt|stop|pause", what, re.I), what
    # HALT does not pass through the question, and neither does anything
    # that stops a camera.
    assert "mayTakeFromRun" not in _fn("    async function haltMotion() {")
