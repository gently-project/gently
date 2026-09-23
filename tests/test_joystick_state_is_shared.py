"""One joystick, one answer.

The lock shipped on the Devices map. Locking it and walking away left nothing
anywhere else to say the joystick was dead — which is the confusion the lock
exists to prevent. So it also belongs in the rig menu, which is reachable from
every page.

Two surfaces for one hardware flag is where the interesting bug lives: each
rendering its own fetch would give three answers to one question (Settings
makes three), and the failure would be silent, because whichever one you are
looking at would still look right. PANELS.md rule 2 — state comes from a
shared store — is what stops that.

What must stay true:

* neither renderer talks to the endpoint itself;
* the stored value is always something the CONTROLLER said, including after a
  failed write; and
* "unknown" stays distinct from "enabled", because a control that guesses
  enabled while the stage is locked sends someone to wiggle a dead joystick.
"""

from __future__ import annotations

import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js"
STORE = (JS / "joystick-state.js").read_text(encoding="utf-8")
DEVICES = (JS / "devices.js").read_text(encoding="utf-8")
RIG = (JS / "rig-menu.js").read_text(encoding="utf-8")
ENDPOINT = "/api/devices/stage/joystick"


def _map_control() -> str:
    m = re.search(r"function setupJoystickLock\(\) \{(.*?)\n    \}\n", DEVICES, re.S)
    assert m, "the map lost its joystick control"
    return m.group(1)


def test_neither_surface_talks_to_the_endpoint_itself() -> None:
    assert ENDPOINT not in _map_control(), (
        "the map fetches the joystick endpoint directly again — it and the rig "
        "menu can now disagree about whether the stage can be moved by hand"
    )
    assert ENDPOINT not in RIG, "the rig menu fetches the endpoint directly"
    assert ENDPOINT in STORE, "the store no longer owns the endpoint"


def test_both_surfaces_render_from_the_store() -> None:
    assert "JoystickState.subscribe(" in _map_control(), "the map no longer subscribes"
    assert "JoystickState.subscribe(" in RIG, "the rig menu no longer subscribes"
    assert "JoystickState.write(" in _map_control() and "JoystickState.write(" in RIG


def test_the_stored_value_is_what_the_controller_said() -> None:
    write = re.search(r"async function write\(enabled\) \{(.*?)\n    \}", STORE, re.S)
    assert write, "the store lost its write"
    body = write.group(1)
    assert "set(!!d.enabled" in body, (
        "the store keeps the value it SENT rather than the one read back — a "
        "lock the hardware refused would be remembered as applied"
    )
    # A failed write must not leave a guess behind.
    assert body.count("await read()") >= 2, (
        "a failed or thrown write leaves the stored state at a guess; the next "
        "decision depends on whether the stage can be nudged by hand"
    )


def test_unknown_is_its_own_state() -> None:
    assert "let _enabled = null" in STORE, "unknown collapsed into a boolean"
    assert "s.enabled === null" in _map_control(), "the map renders unknown as a side"
    assert "s.enabled === null" in RIG, "the rig menu renders unknown as a side"


def test_the_menu_section_retires_when_there_is_nothing_to_say() -> None:
    """Rule 6: no joystick to reach, no row about it."""
    assert "jsSec.hidden = s.enabled === null" in RIG


def test_the_rig_going_away_invalidates_the_answer() -> None:
    assert "DEVICE_LAYER_STATE" in STORE, (
        "the store never hears about the device layer, so a stale 'enabled' "
        "survives the rig being stopped"
    )
