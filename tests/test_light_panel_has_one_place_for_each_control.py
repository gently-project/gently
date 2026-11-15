"""The Light panel has one place for each control, and one line that says what emits.

Emission is conjunctive, and #106 is what happens when someone assumes one
term follows from another:

    emitting = a beam armed AND a line routed AND that line's power > 0

The panel's first shape opened with a mode (LED | Laser | Off) and disclosed
that mode's controls beneath it: beam and power were hidden until a line was
routed, on the argument that they only matter then. It kept a dark panel
short. On the rig it cost three things. The controls moved as the mode
changed, so nothing could be found by place. A line's power could not be seen
or set until the line was routed, which is the moment it starts to matter.
And the facts about emission arrived as separate notes that came and went,
two of them inside a branch that could be closed.

"Need to redesign the light panel", and "the adjustable parameters like laser
power can also have a way to enter numbers into a text box" (2026-11-13). So:
every control is always there, in the same place; every line's power is a
line to drag and a number to type, routed or not; and one line, always
present, says dark, emitting, or what stands in the way.

What is pinned here is what must survive the next redesign too: the state on
screen is the state read back, unknown is never drawn as safe, the panel's
own presses keep to one source, and no fact can be folded out of sight. The
derived logic itself is exercised in tests/js/light-panel.test.mjs.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "gently" / "ui" / "web" / "static" / "js"
CSS = ROOT / "gently" / "ui" / "web" / "static" / "css"
LIGHT = (JS / "panels" / "light.js").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    body = LIGHT[LIGHT.index(f"function {name}(") :]
    return body[: body.index("\n    }")]


# ── what is on screen is what was read ───────────────────────────────────


def test_display_asks_a_narrower_question_than_emission() -> None:
    """`routedLines` is for rendering; `wavelengthsOf` is for safety.

    `wavelengthsOf(null)` returns every line, which is right for `emitting()` —
    an unread config with unread power must come out unknown, not safe. It is
    wrong for the rows, which would all be drawn as routed.
    """
    assert "s.config ?" in _fn("routedLines"), (
        "routedLines no longer distinguishes unknown from empty"
    )
    # emitting() must keep the safe answer
    assert "wavelengthsOf(s.config)" in _fn("emitting")


def test_the_config_is_read_back_not_echoed() -> None:
    """It used to be whatever this panel last wrote.

    `readAll` polled beam and led from hardware; `config` was set by the
    control's own handler, so the whole laser side was an echo of a request
    that returned 200 — the assumption #106 is made of.
    """
    body = _fn("readAll")
    assert "'/api/devices/laser/configs', 'config'" in body, (
        "the current laser config is not read from the device"
    )
    assert "d.current !== 'unknown'" in body, (
        'read() returns the string "unknown" when the group cannot be queried; '
        "that must stay an em dash, not become a preset name"
    )
    wired = _fn("wire")
    assert "SharedState.set" not in wired, "a control is writing its own command back as state"
    assert "classList" not in wired, "a control is lighting itself instead of waiting to be read"


def test_a_preset_is_lit_by_what_was_read_not_by_the_press() -> None:
    row = _fn("presetRow")
    assert "const on = c === s.config;" in row
    assert "b.onclick = () => act(() => route(b.dataset.config));" in _fn("wire")
    # act() re-reads after every write: the response is not evidence.
    assert "await readAll();" in _fn("act")


def test_the_presets_show_what_is_actually_set() -> None:
    """The preset list 503s without a device layer; the read-back config does not.

    Otherwise the row shows no preset lit while the lines under it are drawn
    as routed — the two halves of one panel contradicting each other.
    """
    assert "if (current && !list.includes(current)) list.push(current);" in _fn("presetList")


def test_mode_can_report_both_sources_open() -> None:
    """The fault the panel exists for must not be unrepresentable.

    LED and Laser are separate Micro-Manager config groups (`devices/optical.py`)
    and both can be open — `spim_head_focus` opens the LED on the SPIM camera by
    design, calibration wants the laser. #106 is the two overlapping unnoticed.
    An either/or would hide it.
    """
    body = _fn("mode")
    assert "'both'" in body
    assert "return null" in body, "an unread source must be unknown, not off"


# ── one place for each control ───────────────────────────────────────────


def test_every_control_is_drawn_every_time() -> None:
    """No branch decides whether a control exists; only what it shows."""
    mk = _fn("markup")
    for part in ("${ledRow(s)}", "${presetRow(s)}", "${lineRows(s)}", "${beamRow(s)}"):
        assert part in mk, f"{part} is not always drawn"
    assert "?" not in mk.replace("st.title || ''", ""), (
        "something in the panel is drawn only in some state"
    )


def test_every_line_is_there_and_its_power_can_be_set_before_it_is_routed() -> None:
    rows = _fn("lineRows")
    assert "knownLines().map(wl =>" in rows, "the rows are the routed lines, not the rig's lines"
    assert "const routed = lines.includes(wl);" in rows
    # Routing decides how a row looks. The only thing that turns a row's
    # controls off is a power that has not been read.
    assert rows.count("${val == null ? 'disabled' : ''}") == 2
    assert "routed ? '' : 'disabled'" not in rows and "!routed ? 'disabled'" not in rows
    # So every line's power has to be read, not only the routed ones'.
    assert "for (const wl of knownLines())" in _fn("readAll")


def test_the_limits_are_each_lines_own_from_the_server() -> None:
    rows = _fn("lineRows")
    assert "(limits && limits[wl]) || { min: 0, max: 100 }" in rows
    assert 'min="${lim.min}" max="${lim.max}"' in rows
    assert "/api/devices/laser/limits" in _fn("loadStatics")


def test_a_power_is_a_line_to_drag_and_a_number_to_type() -> None:
    rows = _fn("lineRows")
    assert 'type="range" data-power="${wl}"' in rows
    assert 'data-power-num="${wl}"' in rows and 'class="op-numbox lp-numbox"' in rows
    wire = _fn("wire")
    assert "NumRow.bind(range, box, { onCommit })" in wire
    assert "send('/api/devices/laser/power', { wavelength: wl, pct })" in wire


def test_a_value_is_sent_when_it_is_meant_not_while_it_is_dragged_or_typed() -> None:
    """Every input event would be a hardware write, and "12" on the way to
    "120" would be a power."""
    assert "onInput" not in LIGHT, "something in the Light panel writes on every movement"
    assert "oninput" not in LIGHT


def test_a_readback_does_not_land_under_an_edit() -> None:
    render = _fn("render")
    assert "(rows.get(host) || []).some(r => r.editing())" in render
    assert "waiting.add(host); return;" in render
    # The redraw that waited is drawn when the edit ends, changed or not.
    assert "const settled = () => { if (waiting.has(host)) render(); };" in _fn("wire")


def test_the_keyboard_stays_where_it_was_across_a_redraw() -> None:
    """Each write is followed by a read, and each read redraws the panel.
    Redrawn, the box that was being stepped with the arrow keys was a new
    element without the focus, and the second press went nowhere."""
    render = _fn("render")
    assert "document.activeElement.dataset.k" in render
    assert "again.focus({ preventScroll: true });" in render


# ── one line that says what emits ────────────────────────────────────────


def test_the_line_is_always_there() -> None:
    mk = _fn("markup")
    assert "const st = status(s);" in mk
    assert '<div class="lp-stat is-${st.kind}" role="status"' in mk
    css = (CSS / "operate.css").read_text(encoding="utf-8")
    for kind in ("is-emit", "is-warn", "is-led"):
        assert f".lp-stat.{kind}" in css, f"the status line has no look for {kind}"


def test_the_contradiction_is_stated_rather_than_inferred() -> None:
    """Routed lines with the beam off is the most misleading state possible."""
    body = _fn("status")
    assert "will not emit" in body
    # Name the cause: it is the state every acquisition leaves behind.
    assert "volume acquisition" in body


def test_an_armed_beam_is_never_out_of_sight() -> None:
    """Armed with nothing routed is safe, surprising, and the resting state.

    It was a note inside the laser branch, which `mode()` closes in exactly
    that state. The line it is said on now has no branch to be inside.
    """
    body = _fn("status")
    assert "armed, nothing routed" in body and "nothing emits" in body


def test_not_knowing_is_said_before_anything_reassuring() -> None:
    body = _fn("status")
    unknown = body.index("Emission state unknown")
    assert body.index("EMITTING") < unknown
    for calm in ("Dark — nothing emits", "nothing routed — nothing emits", "will not emit"):
        assert unknown < body.index(calm), f"'{calm}' can be said over an unread light path"


# ── the panel's own presses keep to one source ───────────────────────────


def test_opening_the_led_gates_the_lasers_first_whatever_they_were_doing() -> None:
    """What the laser is doing may be unread, and unknown is what #106 was
    made of."""
    body = _fn("ledSwitch")
    assert "if (open) await send('/api/devices/laser/config', { config: 'ALL OFF' });" in body
    assert body.index("laser/config") < body.index("led/set")
    assert "state: open ? 'Open' : 'Closed'" in body
    # BeamEnabled left alone: setting it No here recreates the #106 state.
    assert "/api/devices/beam" not in body


def test_routing_a_line_closes_the_led_first_unless_it_is_read_as_closed() -> None:
    body = _fn("route")
    assert "wavelengthsOf(config).length && state().led !== 'Closed'" in body, (
        "an LED that is open, or not read, is left open under a routed line"
    )
    assert body.index("led/set") < body.index("laser/config")
    # Choosing a line is not arming the beam, and "off" does not touch the LED.
    assert "/api/devices/beam" not in body
    assert "state: 'Open'" not in body


def test_each_side_of_the_beam_is_its_own_switch() -> None:
    assert "data-beam-side" in _fn("beamRow")
    wire = _fn("wire")
    assert "enabled: b.dataset.beamOn !== 'true', side: b.dataset.beamSide" in wire


# ── unrelated, and kept here since it was found here ─────────────────────


def test_the_device_layer_buttons_do_not_borrow_marking_classes() -> None:
    """They did, and deleting the marking surface took their styling with it.

    The liveness check behind that deletion used a regex requiring a character
    before "marking", so class names STARTING with it were never seen as live.
    `.marking-action-btn` was in use by this strip and its rules were removed.
    """
    html = (ROOT / "gently" / "ui" / "web" / "templates" / "index.html").read_text(encoding="utf-8")
    assert "marking-action-btn" not in html
    assert "marking-done-btn" not in html

    css = (CSS / "main.css").read_text(encoding="utf-8")
    assert ".devices-layer-btn" in css, "the device-layer buttons have no styling"
    assert ".devices-layer-btn.is-primary" in css, "Start lost its primary treatment"
