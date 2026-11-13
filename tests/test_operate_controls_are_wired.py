"""Every control the Operate surface offers must be wired to something.

This test exists because of a specific failure. Consolidating the two roster
renderers into one panel, the roster's own click/keydown listeners had to go —
the panel owns the markup, so it owns the handlers. The deletion was done by
slicing text between two landmarks, and the end landmark matched too late. It
took **eight** unrelated handlers with it:

    op-spim-toggle    start/stop the light-sheet view
    op-calibrate      run the calibration
    [data-gv]         galvo nudges (since then the galvo line, op-gv-in)
    [data-pz]         piezo nudges (since then the piezo line, op-pz-in)
    [data-backoff]    the interlock banner's "Back off 100 µm"
    op-modes          the run-mode chooser
    op-tl-stop        the stop-condition select
    op-lib-list       pick a saved tactic

Every one of those controls still rendered, still looked enabled, and did
nothing. It shipped. CI runs no JavaScript, and nothing else asserted that a
button was connected to a function, so there was no signal at all — the
regression was found only by noticing that clicking a run mode did not change
the run mode.

The lesson is narrow and worth pinning: a rendered control that is not wired is
indistinguishable from a working one until someone presses it. On a microscope,
one of these was a safety control.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE = WEB / "static" / "js" / "operate.js"
INDEX = WEB / "templates" / "index.html"

# Each control, and the token that proves operate.js reaches for it. Ids are
# looked up with $('id'); attribute hooks are queried by selector.
CONTROLS = {
    "op-spim-toggle": "$('op-spim-toggle')",
    "op-halt": "$('op-halt')",
    "op-fd-to": "$('op-fd-to')",
    "op-calibrate": "$('op-calibrate')",
    "op-modes": "$('op-modes')",
    "op-tl-stop": "$('op-tl-stop')",
    "op-lib-list": "$('op-lib-list')",
    "op-run-start": "$('op-run-start')",
    "op-run-pause": "$('op-run-pause')",
    "op-run-stop": "$('op-run-stop')",
    "op-detect": "$('op-detect')",
    "op-confirm": "$('op-confirm')",
    "op-clear": "$('op-clear')",
    "op-cam-toggle": "$('op-cam-toggle')",
    "op-target-scope": "$('op-target-scope')",
    "op-gv-in": "$('op-gv-in')",
    "op-pz-in": "$('op-pz-in')",
    # The same two numbers, typed (panels/numrow.js binds each to its line).
    "op-gv": "$('op-gv')",
    "op-pz": "$('op-pz')",
    # The head, to a typed height.
    "op-fd-go": "$('op-fd-go')",
    "op-fd-goto": "$('op-fd-goto')",
    "[data-mode]": "[data-mode]",
    "[data-lib]": "[data-lib]",
    # Which camera is on screen: the strip above the frame.
    "[data-source]": "#op-source [data-source]",
}


def _wire_body() -> str:
    """Just `wire()`.

    Scoped deliberately. Several of these ids are also read elsewhere — the
    SPIM toggle's label is updated in `applySpim`, for instance — so their mere
    presence in the file proves the control is *mentioned*, not that anything
    listens to it. `wire()` is where listeners are attached, so that is where
    the assertion belongs.
    """
    src = OPERATE.read_text(encoding="utf-8")
    # Anchored on `_wired`, which only the top-level wire() uses. Matching on
    # "function wire() {" finds the gauge factory's inner one first — and
    # landmark-matching text is exactly the mistake that caused the bug this
    # file is about, so it is not repeated here.
    start = src.index("if (_wired) return;")
    end = src.index("\n    async function ", start)
    return src[start:end]


def test_every_control_is_wired_in_wire() -> None:
    body = _wire_body()
    missing = [name for name, token in CONTROLS.items() if token not in body]
    assert not missing, (
        "these controls are not wired in wire(), so they render and do "
        f"nothing when pressed: {missing}"
    )


def test_the_safety_control_is_wired() -> None:
    """`op-halt` stops all stage motion.

    Called out separately because a dead safety button is the worst case: it
    is pressed exactly when something is already wrong. It used to be the
    interlock banner's Back off; that banner and the XY lock behind it were
    removed on 2026-11-08 at the operator's request, and HALT is the one left.
    """
    src = OPERATE.read_text(encoding="utf-8")
    hook = re.search(
        r"\$\('op-halt'\)[^;]*;\s*if \(halt\) halt\.addEventListener\('click',\s*(\w+)", src
    )
    assert hook, "op-halt is not bound to a click handler"
    handler = hook.group(1)
    assert f"function {handler}" in src or f"async function {handler}" in src, (
        f"op-halt is bound to {handler!r}, which is not defined"
    )


def test_the_controls_the_markup_offers_are_the_ones_js_knows() -> None:
    """A control in the template with no counterpart in operate.js is dead."""
    html = INDEX.read_text(encoding="utf-8")

    # Only the Operate surface; other tabs own their own scripts.
    operate = html[html.index('id="devices-view-operate"') : html.index('id="devices-view-map"')]
    ids = set(re.findall(r'id="(op-[a-z0-9-]+)"', operate))

    # Hosts, readouts and containers are written to, not listened on — they are
    # legitimately absent from the handler list.
    interactive = {i for i in ids if i in CONTROLS}
    assert interactive, "no interactive Operate controls found — has the markup moved?"
    body = _wire_body()
    for i in sorted(interactive):
        assert f"$('{i}')" in body, (
            f"{i} exists in the markup but wire() never binds it — it will render and do nothing"
        )


def test_the_view_takes_its_side_from_the_device_layer() -> None:
    """The device layer outlives the page and keeps the live side. A pane that
    assumed A dropped every frame of a stream on B as the other side's and sat
    blank; so the pane asks before its first frame, on entering, and when the
    stream disagrees with it."""
    src = OPERATE.read_text(encoding="utf-8")
    assert "if (!_spimOn) await adoptLsParams();" in src, "view start does not adopt the side"
    assert "onEnter() { adoptLsParams(); }" in src, "entering the pane does not adopt the side"
    assert "getJSON('/api/devices/lightsheet/live/params')" in src, "no read of the live params"
    assert "if (Date.now() - _sideChangedAt > SIDE_SWITCH_MS) adoptLsParams();" in src, (
        "a stream on another side is dropped for good instead of followed"
    )


def test_a_side_pressed_outranks_a_read_that_was_already_in_flight() -> None:
    """The read of the device layer's side takes a moment. A side pressed in
    that moment is newer than the answer on its way; without asking again
    after the wait, the answer put the strip back on the side just left. The
    strip made this easy to hit: it enters the surface and chooses the side
    in one press."""
    src = OPERATE.read_text(encoding="utf-8")
    fn = src[src.index("    function adoptLsParams() {") :]
    fn = fn[: fn.index("\n    }")]
    guard = "if (Date.now() - _sideChangedAt < SIDE_SWITCH_MS) return;"
    assert fn.count(guard) == 2, "the switch window is not asked about again after the read"
    first = fn.index(guard)
    read = fn.index("await getJSON('/api/devices/lightsheet/live/params')")
    assert first < read < fn.index(guard, first + 1)
    # And the strip tells the device layer before it enters the surface.
    choose = src[src.index("    function chooseSource(src) {") :]
    choose = choose[: choose.index("\n    }")]
    assert choose.index("setSpimSide(src)") < choose.index("showPane('spim')")
