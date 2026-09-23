"""The joystick lock is reachable where the stage is.

It existed — `GET/POST /api/devices/stage/joystick`, written to the Tiger
controller and read back, persisted so a boot re-applies the operator's choice
rather than forcing the joystick on — but the only control for it was a
checkbox in Settings. That is not where anyone is standing when they wonder
why the physical controller does nothing, or when they want it to stop working
while a run is on.

What must stay true:

* the state shown is READ BACK from the controller, never the command that was
  sent (PANELS rule 3) — this one matters more than usual, because the failure
  mode is a UI claiming a lock the hardware refused while someone leans on the
  joystick; and
* a failed write re-reads rather than guessing, so the button never settles
  into a state nobody confirmed.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
DEVICES_JS = WEB / "static" / "js" / "devices.js"
INDEX = WEB / "templates" / "index.html"


def _setup() -> str:
    js = DEVICES_JS.read_text(encoding="utf-8")
    m = re.search(r"function setupJoystickLock\(\) \{(.*?)\n    \}\n", js, re.S)
    assert m, "the map lost its joystick control"
    return m.group(1)


def test_the_control_is_on_the_map() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert 'id="devices-js-toggle"' in html, "no joystick control on the map"
    js = DEVICES_JS.read_text(encoding="utf-8")
    assert "setupJoystickLock();" in js, "the control is never wired up"


def test_what_is_shown_comes_from_the_shared_store() -> None:
    """Read-back now lives in JoystickState, which the rig menu shares.

    The assertion that the rendered value is the one the CONTROLLER reported
    moved with it — see tests/test_joystick_state_is_shared.py. What belongs
    here is that this surface renders from the store rather than growing its
    own copy, because a second copy is how two surfaces start disagreeing.
    """
    body = _setup()
    assert "JoystickState.subscribe(" in body, "the map no longer renders from the store"
    assert "/api/devices/stage/joystick" not in body, "the map fetches the endpoint directly again"


def test_the_write_goes_through_the_store() -> None:
    """Failure handling moved with the write; the button just asks."""
    body = _setup()
    assert "JoystickState.write(" in body, "the map writes to the controller itself again"


def test_the_locked_state_is_visible_as_a_state() -> None:
    """ "Why is the joystick dead?" should be answerable from across the room."""
    body = _setup()
    assert "aria-pressed" in body, "the lock is not exposed as a pressed state"
    css = (WEB / "static" / "css" / "devices.css").read_text(encoding="utf-8")
    assert '.devices-js-btn[aria-pressed="true"]' in css, (
        "a locked joystick looks identical to an enabled one"
    )


def test_every_control_for_one_flag_reaches_one_endpoint() -> None:
    """Three surfaces now: Settings, the map, the rig menu.

    Settings is a separate page with its own script and still calls the
    endpoint directly; the two inside the app go through the shared store.
    What must hold is that there is exactly one endpoint between them.
    """
    settings = (WEB / "templates" / "settings.html").read_text(encoding="utf-8")
    store = (WEB / "static" / "js" / "joystick-state.js").read_text(encoding="utf-8")
    assert "/api/devices/stage/joystick" in settings
    assert "/api/devices/stage/joystick" in store
