"""A live view is off once you leave its surface, and stays off.

"i went back to spim head view to notice that the camera is running there in
live mode ... the camera should stop live when i leave the surface of that
view." — "the simplest fix is if we change tabs, the live view is off."

Leaving always stopped the camera. But each view came with a remembered "was
on", so returning restarted it: fourteen minutes into a timelapse the SPIM
camera began streaming under the run, and the Calibration pane — which has no
image to show one on — restarted the stream unseen.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
OPERATE = (JS / "operate.js").read_text(encoding="utf-8")
DEVICES = (JS / "devices.js").read_text(encoding="utf-8")


def _panes() -> str:
    start = OPERATE.index("    const PANES = {")
    return OPERATE[start : OPERATE.index("    function stopBottom()", start)]


def _pane(name: str) -> str:
    panes = _panes()
    start = panes.index(f"        {name}: {{")
    return panes[start : panes.index("        },", start)]


def test_nothing_remembers_that_a_view_was_on():
    assert "WasOn" not in OPERATE


def test_entering_a_surface_never_starts_a_camera():
    for name in ("bottom", "spim", "cal", "acquire"):
        enter = re.search(r"onEnter\(\) \{(.*?)\},?\n", _pane(name), re.S)
        assert enter, f"{name} has no onEnter"
        body = enter.group(1)
        assert "toggleSpim" not in body and "toggleBottomCam" not in body, (
            f"entering {name} starts a camera"
        )
        assert "live/start" not in body and "stream/start" not in body


def test_leaving_a_camera_surface_stops_its_view():
    assert "onLeave() { if (_bottomOn) stopBottom(); }" in _pane("bottom")
    assert "if (_spimOn) stopSpim();" in _pane("spim")
    assert "onLeave() { if (_spimOn) stopSpim(); forceLedOff(); }" in _pane("cal")


def test_choosing_the_other_camera_stops_this_one_and_starts_nothing():
    """The two cameras are one workspace now, and one strip chooses between
    them. Choosing is leaving one surface for the other: the view that was
    live stops, and the one arrived at waits for its Start."""
    fn = OPERATE[OPERATE.index("    function chooseSource(src) {") :]
    fn = fn[: fn.index("\n    }")]
    assert "showPane('bottom')" in fn and "showPane('spim')" in fn
    assert "toggleSpim" not in fn and "toggleBottomCam" not in fn
    assert "live/start" not in fn and "stream/start" not in fn
    show = OPERATE[OPERATE.index("    function showPane(name) {") :]
    show = show[: show.index("\n    }")]
    assert "PANES[prev].onLeave(name);" in show


def test_the_led_is_left_alone_between_the_cameras_and_closed_on_leaving_scope():
    """It lights the bottom camera too, and the Light panel beside the frame
    goes on saying what it is. Leaving Scope closes it, as leaving the SPIM
    head always did. So does going to Fit, which is on Scope now: under the
    LED alone a calibration has no nuclei to find."""
    assert (
        "onLeave(to) { if (_spimOn) stopSpim(); if (!inScope(to) || to === 'cal') forceLedOff(); }"
    ) in _pane("spim")


def test_leaving_operate_altogether_stops_both():
    fn = OPERATE[OPERATE.index("    function deactivate() {") :][:500]
    assert "if (_bottomOn) stopBottom();" in fn
    assert "if (_spimOn) stopSpim();" in fn
    assert "forceLedOff();" in fn


def test_only_the_buttons_start_a_view():
    """toggleSpim / toggleBottomCam are called from their buttons and nowhere else."""
    for fn, button in (("toggleSpim", "op-spim-toggle"), ("toggleBottomCam", "op-cam-toggle")):
        uses = [ln.strip() for ln in OPERATE.splitlines() if fn in ln]
        assert len(uses) == 2, f"{fn} is used somewhere besides its button: {uses}"
        assert uses[0].startswith(f"async function {fn}()")
        assert re.search(rf"\$\('{button}'\);[^\n]*addEventListener\('click', {fn}\)", OPERATE)


def test_leaving_the_devices_tab_is_leaving_every_surface_in_it():
    """The rail switched tabs without telling Operate: a camera started on
    Devices kept streaming behind Embryos or Home."""
    assert "ClientEventBus.on('TAB_CHANGED', onTabChanged);" in DEVICES
    fn = DEVICES[DEVICES.index("    function onTabChanged(tab) {") :][:400]
    assert "if (tab !== 'devices') OperateManager.deactivate();" in fn
    assert "else if (_currentView === 'operate') OperateManager.activate();" in fn
