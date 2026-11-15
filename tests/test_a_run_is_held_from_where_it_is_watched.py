"""A run is held from wherever it is said.

The pictures of a run are on the Embryos tab, which could neither pause nor
stop one. Pause and Stop were on the Acquisition surface, which had no
picture. Neither pointed at the other (docs/workspace/
calibration-and-acquisition.md, A6).

Any element with `data-run-control` is one of the run's controls, drawn and
answered by the shell, which already knows the run: Pause in the Devices
toolbar beside the words that say it, and Pause and Stop on the Embryos tab,
with the way to where a run is planned while none is going.

Checked on the simulated rig: a brightfield run paused from the toolbar on
Scope, resumed and stopped from the Embryos tab.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
SHELL = (WEB / "static" / "js" / "shell.js").read_text(encoding="utf-8")
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OP_CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")
MAIN_CSS = (WEB / "static" / "css" / "main.css").read_text(encoding="utf-8")


def _fn(head: str) -> str:
    start = SHELL.index(head)
    nxt = re.search(r"\n    (?:async )?function |\n    // ── ", SHELL[start + len(head) :])
    return SHELL[start : start + len(head) + (nxt.start() if nxt else 0)]


def test_pause_is_in_the_devices_toolbar_beside_the_words_that_say_the_run():
    said = HTML.index('id="devices-run"')
    pause = HTML.index('class="devices-runbtn"')
    halt = HTML.index('id="op-halt"')
    assert said < pause < halt
    tag = HTML[pause - 8 : HTML.index(">", pause)]
    assert 'data-run-control="pause"' in tag and "hidden" in tag


def test_the_tab_a_run_is_watched_on_can_pause_and_stop_it():
    head = HTML[HTML.index('id="embryos-header-panel"') : HTML.index('id="header-stats"')]
    box = head[head.index('id="embryos-run-controls"') :]
    for what in ("pause", "stop", "plan"):
        assert f'data-run-control="{what}"' in box, what
    # Pause and Stop are not drawn until there is a run to hold.
    for what in ("pause", "stop"):
        tag = box[box.index(f'data-run-control="{what}"') - 60 :]
        assert "hidden" in tag[: tag.index(">")], what


def test_the_shell_draws_them_from_the_runs_state():
    draw = _fn("    function renderRunControls() {")
    assert "document.querySelectorAll('[data-run-control]')" in draw
    assert "if (what === 'plan') { b.hidden = going; return; }" in draw
    assert "b.hidden = !going;" in draw
    assert "_run.status === 'paused' ? 'Resume' : 'Pause'" in draw
    # Redrawn whenever the run is.
    assert "renderRunControls();" in _fn("    function renderStrip(status) {")


def test_the_shell_answers_them():
    act = _fn("    async function runControl(what, b) {")
    assert "'/api/devices/timelapse/stop'" in act
    assert "paused ? '/api/devices/timelapse/resume' : '/api/devices/timelapse/pause'" in act
    # Stopping a night's run is asked about; pausing it is not.
    assert "if (what === 'stop' && !window.confirm('Stop the run?')) return;" in act
    # And it says what happened, then reads the run again.
    assert "pollRun();" in act and "say(" in act
    # One listener, for wherever a surface puts them.
    assert "const b = e.target.closest('[data-run-control]');" in SHELL


def test_with_no_run_going_the_tab_points_at_where_one_is_planned():
    act = _fn("    async function runControl(what, b) {")
    plan = act[act.index("if (what === 'plan') {") :][:400]
    assert "switchTab('devices')" in plan
    assert "OperateManager.roster.goTo('acquire')" in plan


def test_a_hidden_control_is_hidden():
    # A class that sets display beats [hidden].
    assert ".devices-runbtn[hidden] { display: none; }" in OP_CSS
    assert ".run-controls [hidden] { display: none; }" in MAIN_CSS
