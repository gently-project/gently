"""The LED's brightness is set on the ASI Tiger, and read back from it.

The LED was a shutter to gently: Open or Closed, at whatever brightness the
controller happened to hold. The Tiger adapter has had a brightness property
all along (`LED Intensity(%)`, ASILED.cpp), so this writes that property
directly rather than adding preset levels to the `LED` config group.

Three things are easy to get wrong, and each has a test here:

- 0 is not a brightness. The controller reports 0 for an LED that is off, and
  the adapter's own limits start at 1, so dark is `Closed`.
- Setting the brightness must not open or close the LED. The adapter holds a
  value set while closed and applies it on the next open.
- A status read must survive an LED whose brightness cannot be read. Open or
  Closed is still true, and the Light panel's mode depends on it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("aiohttp")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import gently.ui.web.auth as auth  # noqa: E402
from gently.hardware.dispim.device_layer import DeviceLayerServer  # noqa: E402
from gently.hardware.dispim.devices.optical import DiSPIMLED  # noqa: E402
from gently.ui.web.routes.data import create_router  # noqa: E402

LED_NAME = "LED:X:31"
PROP = "LED Intensity(%)"
LIGHT_JS = (
    Path(__file__).resolve().parents[1]
    / "gently"
    / "ui"
    / "web"
    / "static"
    / "js"
    / "panels"
    / "light.js"
).read_text(encoding="utf-8")


class _Core:
    """The slice of CMMCore the LED touches."""

    def __init__(self, intensity="50", readable=True):
        self.props = {(LED_NAME, PROP): intensity}
        self.readable = readable
        self.config = "Closed"
        self.calls: list[tuple] = []

    def getAvailableConfigs(self, group):  # noqa: N802
        return ["Open", "Closed"]

    def getCurrentConfig(self, group):  # noqa: N802
        return self.config

    def setConfig(self, group, config):  # noqa: N802
        self.calls.append(("setConfig", group, config))
        self.config = config

    def waitForConfig(self, group, config):  # noqa: N802
        pass

    def setProperty(self, dev, prop, val):  # noqa: N802
        self.calls.append(("setProperty", dev, prop, val))
        self.props[(dev, prop)] = str(val)

    def getProperty(self, dev, prop):  # noqa: N802
        if not self.readable:
            raise RuntimeError(f'No property "{prop}" on device "{dev}"')
        return self.props[(dev, prop)]


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


def _led(core=None) -> tuple[DiSPIMLED, _Core]:
    core = core or _Core()
    return DiSPIMLED(core=core, name=LED_NAME, group_name="LED"), core


def _dl(core=None) -> tuple[DeviceLayerServer, _Core]:
    led, core = _led(core)
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.devices = {"led": led}
    return dl, core


def _body(resp) -> dict:
    return json.loads(resp.text)


# ---------------------------------------------------------------------------
# The device
# ---------------------------------------------------------------------------


class TestTheDevice:
    def test_it_writes_the_tigers_own_property(self):
        led, core = _led()
        led.set_intensity_pct(30)
        assert core.calls == [("setProperty", LED_NAME, PROP, 30)]

    def test_it_is_read_back_from_the_device(self):
        led, _ = _led()
        led.set_intensity_pct(72)
        assert led.get_intensity_pct() == 72

    @pytest.mark.parametrize("pct", [1, 100])
    def test_the_limits_are_inclusive(self, pct):
        led, _ = _led()
        led.set_intensity_pct(pct)
        assert led.get_intensity_pct() == pct

    @pytest.mark.parametrize("pct", [0, -5, 101, 1000])
    def test_out_of_range_is_refused_before_the_hardware(self, pct):
        led, core = _led()
        with pytest.raises(ValueError, match="outside"):
            led.set_intensity_pct(pct)
        assert core.calls == []

    def test_zero_is_told_how_to_turn_the_led_off(self):
        led, _ = _led()
        with pytest.raises(ValueError, match="Closed"):
            led.set_intensity_pct(0)

    @pytest.mark.parametrize("pct", [12.5, True, None, "bright"])
    def test_only_a_whole_percent_is_a_brightness(self, pct):
        led, core = _led()
        with pytest.raises(ValueError):
            led.set_intensity_pct(pct)
        assert core.calls == []

    def test_a_whole_float_is_a_whole_percent(self):
        """A slider hands over 40.0, and JSON does not tell the two apart."""
        led, core = _led()
        led.set_intensity_pct(40.0)
        assert core.calls == [("setProperty", LED_NAME, PROP, 40)]

    def test_it_does_not_open_or_close_the_led(self):
        led, core = _led()
        led.set_intensity_pct(30)
        assert not [c for c in core.calls if c[0] == "setConfig"]
        assert core.config == "Closed"


# ---------------------------------------------------------------------------
# The device layer
# ---------------------------------------------------------------------------


class TestTheDeviceLayer:
    def test_set_answers_with_what_the_device_holds(self):
        dl, core = _dl()
        resp = asyncio.run(dl.handle_set_led_intensity(_Req({"pct": 25})))
        assert resp.status == 200
        assert _body(resp) == {"success": True, "pct": 25, "readback_pct": 25}
        assert core.props[(LED_NAME, PROP)] == "25"

    @pytest.mark.parametrize("body", [{"pct": 0}, {"pct": 101}, {"pct": 12.5}, {}])
    def test_a_refused_value_is_a_400_not_a_500(self, body):
        dl, core = _dl()
        resp = asyncio.run(dl.handle_set_led_intensity(_Req(body)))
        assert resp.status == 400
        assert _body(resp)["success"] is False
        assert core.calls == []

    def test_no_led_is_said(self):
        dl, _ = _dl()
        dl.devices = {}
        resp = asyncio.run(dl.handle_set_led_intensity(_Req({"pct": 25})))
        assert resp.status == 503 and "LED device not found" in _body(resp)["error"]

    def test_status_carries_the_brightness_and_its_bounds(self):
        dl, _ = _dl(_Core(intensity="64"))
        body = _body(asyncio.run(dl.handle_get_led_status(None)))
        assert body["success"] is True
        assert body["current_state"] == "Closed"
        assert body["intensity_pct"] == 64
        assert body["intensity_limits_pct"] == {"min": 1, "max": 100}

    def test_an_unreadable_brightness_does_not_cost_the_state(self):
        dl, _ = _dl(_Core(readable=False))
        body = _body(asyncio.run(dl.handle_get_led_status(None)))
        assert body["success"] is True
        assert body["current_state"] == "Closed"
        assert body["intensity_pct"] is None

    def test_the_route_is_registered(self):
        src = Path(DeviceLayerServer.__module__.replace(".", "/") + ".py")
        text = (Path(__file__).resolve().parents[1] / src).read_text(encoding="utf-8")
        assert 'add_post("/api/led/intensity", self.handle_set_led_intensity)' in text


# ---------------------------------------------------------------------------
# The web route
# ---------------------------------------------------------------------------


def _app(client=None, control=True):
    server = MagicMock()
    server.agent_bridge.agent.client = client
    app = FastAPI()
    app.include_router(create_router(server))
    if control:
        app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


class TestTheWebRoute:
    def test_it_forwards_to_the_client(self):
        client = MagicMock()
        client.set_led_intensity = AsyncMock(return_value={"success": True, "readback_pct": 30})
        r = _app(client).post("/api/devices/led/intensity", json={"pct": 30})
        assert r.status_code == 200 and r.json()["readback_pct"] == 30
        client.set_led_intensity.assert_awaited_once_with(30)

    @pytest.mark.parametrize("body", [{}, {"pct": "bright"}, {"pct": None}])
    def test_a_body_with_no_number_is_a_400(self, body):
        client = MagicMock()
        client.set_led_intensity = AsyncMock()
        r = _app(client).post("/api/devices/led/intensity", json=body)
        assert r.status_code == 400
        client.set_led_intensity.assert_not_awaited()

    def test_a_client_that_raises_is_a_502(self):
        client = MagicMock()
        client.set_led_intensity = AsyncMock(side_effect=RuntimeError("timed out"))
        r = _app(client).post("/api/devices/led/intensity", json={"pct": 30})
        assert r.status_code == 502


# ---------------------------------------------------------------------------
# The agent's tool
# ---------------------------------------------------------------------------


def _tool(name):
    import gently.app.tools.led_tools  # noqa: F401  (registers on import)
    from gently.harness.tools.registry import get_tool_registry

    return get_tool_registry()._tools[name].handler


class TestTheTool:
    async def test_it_reports_the_readback(self):
        client = MagicMock()
        client.set_led_intensity = AsyncMock(return_value={"success": True, "readback_pct": 20})
        out = await _tool("set_led_intensity")(pct=20, context={"client": client})
        assert out == "LED intensity set to 20% (readback: 20%)"
        client.set_led_intensity.assert_awaited_once_with(20)

    async def test_a_refusal_reaches_the_agent_in_the_devices_words(self):
        client = MagicMock()
        client.set_led_intensity = AsyncMock(
            return_value={"success": False, "error": "LED intensity 0% outside [1, 100]%."}
        )
        out = await _tool("set_led_intensity")(pct=0, context={"client": client})
        assert "outside [1, 100]" in out

    async def test_status_says_the_brightness(self):
        client = MagicMock()
        client.get_led_status = AsyncMock(
            return_value={"success": True, "current_state": "Open", "intensity_pct": 45}
        )
        out = await _tool("get_led_status")(context={"client": client})
        assert "Current state: Open" in out and "Intensity: 45%" in out

    async def test_status_does_not_invent_a_brightness(self):
        client = MagicMock()
        client.get_led_status = AsyncMock(
            return_value={"success": True, "current_state": "Open", "intensity_pct": None}
        )
        out = await _tool("get_led_status")(context={"client": client})
        assert "Intensity: unknown" in out


# ---------------------------------------------------------------------------
# The Light panel
# ---------------------------------------------------------------------------


def _fn(name: str) -> str:
    body = LIGHT_JS[LIGHT_JS.index(f"function {name}(") :]
    return body[: body.index("\n    }")]


def _led_row() -> str:
    """The LED's row: its switch and its brightness."""
    return _fn("ledRow")


class TestThePanel:
    def test_the_brightness_writes_to_the_route_that_exists(self):
        assert "send('/api/devices/led/intensity', { pct })" in _fn("wire")

    def test_it_writes_when_the_value_is_meant_not_while_it_is_dragged_or_typed(self):
        """Every input event would be a serial write to the controller, and a
        number half typed is not the number meant."""
        wire = _fn("wire")
        assert "NumRow.bind(range, box, { onCommit })" in wire
        assert "onInput" not in LIGHT_JS and "oninput" not in LIGHT_JS

    def test_the_brightness_can_be_dragged_or_typed(self):
        row = _led_row()
        assert 'type="range" data-led-pct' in row
        assert "data-led-num" in row and 'class="op-numbox lp-numbox"' in row
        assert "pair(ledPct, el.querySelector('[data-led-num]')," in _fn("wire")

    def test_the_brightness_is_read_from_the_status_the_panel_already_asks_for(self):
        """One request answers both: the device layer is slow to read."""
        assert "d.intensity_pct" in LIGHT_JS
        assert LIGHT_JS.count("'/api/devices/led/status'") == 1
        assert _fn("readAll").count("/api/devices/led/") == 1

    def test_an_unread_brightness_is_a_dash_and_a_dead_slider(self):
        row = _led_row()
        assert row.count("${val == null ? 'disabled' : ''}") == 2, "the line or its number is live"
        assert "${val == null ? '—' : val}" in row

    def test_the_bounds_come_from_the_server(self):
        row = _led_row()
        assert "s.ledLim ||" in row
        assert 'min="${lim.min}" max="${lim.max}" step="1"' in row

    def test_a_closed_led_says_why_the_image_did_not_change(self):
        """The adapter holds a brightness set while closed and applies it on
        the next open, so the slider moves and the picture does not. The unit
        says so; it was a sentence under the slider."""
        row = _led_row()
        assert "s.led === 'Closed' && val != null ? '% when open' : '%'" in row
        assert "this is the brightness it will open at" in row

    def test_the_panel_no_longer_says_there_is_no_control(self):
        assert "no intensity control" not in LIGHT_JS


# ---------------------------------------------------------------------------
# The LED, beside either camera
# ---------------------------------------------------------------------------

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE_JS = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
SCOPE = INDEX[INDEX.index('id="op-pane-scope"') : INDEX.index('id="op-pane-cal"')]


class TestTheLedBesideEitherCamera:
    """The bottom camera is lit by the LED, and had no way to dim it.

    So it got a card: the Light panel mounted a second time, showing the LED
    alone (`only: 'led'`), on the Bottom cam pane. The pane and the SPIM head
    are one workspace now, with the whole Light panel beside whichever camera
    is on screen, and the card and the narrower window are gone: one subject,
    one panel, one mount (docs/architecture/PANELS.md rules 1 and 2).
    """

    def test_there_is_one_light_panel_and_it_is_on_scope(self):
        assert 'id="op-light-host"' in SCOPE
        assert INDEX.count('id="op-light-host"') == 1
        assert 'id="op-led-host"' not in INDEX
        assert "only: 'led'" not in OPERATE_JS and "opts.only" not in LIGHT_JS

    def test_it_is_mounted_with_the_panels_not_on_entering_a_surface(self):
        """`mountLightPanel` used to wait for the SPIM pane, so on the pane the
        page starts on there was nothing to read the LED with."""
        body = OPERATE_JS[OPERATE_JS.index("function mountPanels()") :]
        body = body[: body.index("\n    }")]
        assert "mountLightPanel();" in body
        show = OPERATE_JS[OPERATE_JS.index("    function showPane(name) {") :]
        assert "mountLightPanel" not in show[: show.index("\n    }")]

    def test_the_led_has_a_switch_that_shows_what_was_read(self):
        """On the bottom pane the LED was once read-only: it read Closed after
        any visit to the SPIM pane (leaving closed it) and nothing there could
        open it."""
        row = _led_row()
        assert "['Closed', 'Open'].map(v =>" in row
        assert "const on = s.led === v;" in row
        assert 'data-led-switch="${v}"' in row
        assert "act(() => ledSwitch(b.dataset.ledSwitch === 'Open'))" in _fn("wire")

    def test_opening_the_led_gates_the_lasers_first_whatever_they_were_doing(self):
        """What the laser is doing may be unread, and unknown is what #106
        was made of."""
        body = _fn("ledSwitch")
        assert "if (open) await send('/api/devices/laser/config', { config: 'ALL OFF' });" in body
        assert body.index("laser/config") < body.index("led/set")
        assert "state: open ? 'Open' : 'Closed'" in body

    def test_a_panel_nobody_is_looking_at_reads_nothing(self):
        body = LIGHT_JS[LIGHT_JS.index("    async function mount(hostId) {") :]
        body = body[: body.index("\n    }")]
        assert "if (visible()) refresh();" in body
        assert "el.offsetParent !== null" in _fn("visible")

    def test_other_callers_refresh_still_reads_everything(self):
        """operate.js calls `LightPanel.refresh()` after it closes the LED."""
        assert "await readAll();" in _fn("refresh")
        assert "mount, unmount, refresh, emitting, mode, status, wavelengthsOf," in LIGHT_JS
        assert "LightPanel.refresh()" in OPERATE_JS
