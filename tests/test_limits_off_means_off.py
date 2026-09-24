"""XY limits OFF means the controller's own limits — not a box of ours.

Reported from the rig after the firmware fence was made opt-in: "greater
freedom of movement, but still not able to cover the full extent". Ryan was
right, and the reason was in the code all along: "off" wrote the
`XY_STAGE_*_UM` constants into the Tiger as if they were the stage's travel.
They are not. The comment above them says they are INSET ~850 µm from a
hand-measured safe area, to absorb joystick overshoot. Off was a fence at
Gently's most conservative numbers.

The Tiger has a real "off". `SL X-` / `SU X-` restore an axis's default limit
(Tiger firmware ≥ 2.8; ±110 mm on a stock controller, past the travel), and
after it only the hardware limit switches stop the joystick. The ASI adapter's
limit properties cannot say `-`, so it goes through the hub's serial
passthrough — whose reply the adapter never checks, so we do.

Everything here runs against a fake controller. Nothing in this file has
touched hardware; that is Ryan's job, and the checks in
`restore_firmware_limit_defaults` are what make it safe to hand him.
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

pytest.importorskip("aiohttp")

from gently.hardware.dispim.device_layer import DeviceLayerServer  # noqa: E402
from gently.hardware.dispim.devices.stage import (  # noqa: E402
    XY_STAGE_X_MAX_UM,
    XY_STAGE_X_MIN_UM,
    XY_STAGE_Y_MAX_UM,
    XY_STAGE_Y_MIN_UM,
    DiSPIMXYStage,
    HardwareError,
)

HUB = "TigerCommHub"
STAGE = "XYStage:XY:31"
REGION = {"x_min": -900.0, "x_max": 400.0, "y_min": -800.0, "y_max": 100.0}
INSET = {
    "x_min": XY_STAGE_X_MIN_UM,
    "x_max": XY_STAGE_X_MAX_UM,
    "y_min": XY_STAGE_Y_MIN_UM,
    "y_max": XY_STAGE_Y_MAX_UM,
}


class _Tiger:
    """The controller, as far as SL/SU are concerned. Values in mm."""

    def __init__(self, held_um=INSET, defaults_mm=(-110.0, 110.0)):
        self.lo = {"X": held_um["x_min"] / 1000, "Y": held_um["y_min"] / 1000}
        self.hi = {"X": held_um["x_max"] / 1000, "Y": held_um["y_max"] / 1000}
        self.default_lo = {"X": defaults_mm[0], "Y": defaults_mm[0]}
        self.default_hi = {"X": defaults_mm[1], "Y": defaults_mm[1]}
        self.reject: set[str] = set()  # commands answered with :N

    def handle(self, cmd: str) -> str:
        if cmd in self.reject:
            return ":N -4"
        m = re.match(r"^(SL|SU) (.*)$", cmd.strip())
        if not m:
            return ":N -1"
        table, defaults = (
            (self.lo, self.default_lo) if m.group(1) == "SL" else (self.hi, self.default_hi)
        )
        out = []
        for tok in m.group(2).split():
            axis, op = tok[0], tok[1:]
            if op == "?":
                out.append(f"{axis}={table[axis]:.4f}")
            elif op == "-":
                table[axis] = defaults[axis]
            elif op.startswith("="):
                table[axis] = float(op[1:])
            else:
                return ":N -1"
        return ":A " + " ".join(out) if out else ":A"


class _Core:
    """MMCore with a Tiger behind the hub's SerialCommand property.

    The limit PROPERTIES answer from a cache, like the real adapter does with
    RefreshPropertyValues off — so a test can tell whether the code asked the
    controller or the cache.
    """

    def __init__(self, tiger: _Tiger, xy_um=(0.0, 0.0)):
        self.tiger = tiger
        self.xy = xy_um
        self.props: dict[tuple[str, str], str] = {(HUB, "OnlySendSerialCommandOnChange"): "Yes"}
        self.sent: list[tuple[str, str]] = []  # (command, OnlySendSerialCommandOnChange at send)
        self.property_reads: list[str] = []

    def getParentLabel(self, label):  # noqa: N802
        return HUB if label == STAGE else ""

    def setProperty(self, dev, prop, val):  # noqa: N802
        if dev == HUB and prop == "SerialCommand":
            only = self.props.get((HUB, "OnlySendSerialCommandOnChange"))
            self.sent.append((str(val), only))
            self.props[(HUB, "SerialResponse")] = self.tiger.handle(str(val))
            return
        if dev == STAGE and prop.endswith("(mm)"):
            axis = prop[-5]
            table = self.tiger.lo if prop.startswith("Lower") else self.tiger.hi
            table[axis] = float(val)
        self.props[(dev, prop)] = str(val)

    def getProperty(self, dev, prop):  # noqa: N802
        self.property_reads.append(prop)
        return self.props[(dev, prop)]

    def getXYPosition(self, *_):  # noqa: N802
        return self.xy


def _stage(core: _Core) -> DiSPIMXYStage:
    st = DiSPIMXYStage(name=STAGE, core=core)  # type: ignore[arg-type]
    st.read = lambda: {st.name: {"value": core.xy}}  # type: ignore[method-assign]
    return st


def _um(box_mm_lo, box_mm_hi):
    return {
        "x_min": box_mm_lo["X"] * 1000,
        "x_max": box_mm_hi["X"] * 1000,
        "y_min": box_mm_lo["Y"] * 1000,
        "y_max": box_mm_hi["Y"] * 1000,
    }


# ---------------------------------------------------------------------------
# The stage primitive
# ---------------------------------------------------------------------------


def test_off_is_the_controllers_own_default_and_nothing_of_ours():
    tiger = _Tiger()
    core = _Core(tiger)
    st = _stage(core)

    got = st.restore_firmware_limit_defaults()

    commands = [c for c, _ in core.sent]
    assert "SL X- Y-" in commands and "SU X- Y-" in commands, commands
    assert commands.index("SL X- Y-") < commands.index("SU X- Y-")
    assert got == {"x_min": -110_000.0, "x_max": 110_000.0, "y_min": -110_000.0, "y_max": 110_000.0}
    assert st.firmware_box == got
    # and no number of ours went anywhere near the controller
    assert not any("=" in c for c in commands), commands


def test_the_same_command_twice_is_not_dropped():
    """The adapter drops a repeated SerialCommand unless told otherwise."""
    core = _Core(_Tiger())
    _stage(core).restore_firmware_limit_defaults()
    assert all(only == "No" for _, only in core.sent), core.sent


def test_a_rejected_command_is_an_error_not_a_shrug():
    """The adapter stores `:N …` in SerialResponse and raises nothing."""
    tiger = _Tiger()
    tiger.reject.add("SL X- Y-")
    core = _Core(tiger)
    with pytest.raises(HardwareError, match="rejected"):
        _stage(core).restore_firmware_limit_defaults()
    assert "SU X- Y-" not in [c for c, _ in core.sent], "it carried on after a refusal"


def test_defaults_narrower_than_what_was_held_are_refused():
    """An "off" that fences tighter is a fault, not a feature."""
    tiger = _Tiger(defaults_mm=(-1.0, 0.5))  # inside the inset box
    with pytest.raises(HardwareError, match="narrower"):
        _stage(_Core(tiger)).restore_firmware_limit_defaults()


def test_a_stage_outside_the_defaults_is_refused():
    tiger = _Tiger(defaults_mm=(-1.0, 1.0))
    tiger.lo = {"X": -0.5, "Y": -0.5}  # held box narrower than the defaults
    tiger.hi = {"X": 0.5, "Y": 0.5}
    core = _Core(tiger, xy_um=(1500.0, 0.0))  # but the stage is beyond them
    with pytest.raises(HardwareError, match="outside"):
        _stage(core).restore_firmware_limit_defaults()


def test_restoring_the_controller_leaves_gentlys_own_fence_alone():
    """Two fences. This touches one of them."""
    st = _stage(_Core(_Tiger()))
    st.set_software_limits(REGION["x_min"], REGION["x_max"], REGION["y_min"], REGION["y_max"])
    st.restore_firmware_limit_defaults()
    assert st.x_limits == (REGION["x_min"], REGION["x_max"])
    assert st.y_limits == (REGION["y_min"], REGION["y_max"])


def test_the_controller_is_asked_not_the_adapters_cache():
    """`LowerLimX(mm)` answers from a cache unless RefreshPropertyValues is on.

    After `SL X-` that cache still says the old number. The only reading that
    cannot be stale is the serial query.
    """
    core = _Core(_Tiger())
    st = _stage(core)
    st.read_firmware_limits()
    assert not any(p.endswith("(mm)") for p in core.property_reads), core.property_reads
    assert [c for c, _ in core.sent] == ["SL X? Y?", "SU X? Y?"]


def test_sl_su_are_sent_without_a_card_address():
    """Axis-specific commands are routed by the COMM card. ASI says not to
    prefix them, and the adapter never does for its own SL/SU reads."""
    core = _Core(_Tiger())
    _stage(core).restore_firmware_limit_defaults()
    for c, _ in core.sent:
        assert re.match(r"^S[LU] [XY]", c), f"addressed or malformed: {c!r}"


# ---------------------------------------------------------------------------
# The device layer
# ---------------------------------------------------------------------------


def _dl(stage, tmp_path, env=None):
    dl = DeviceLayerServer.__new__(DeviceLayerServer)
    dl.devices = {"xy_stage": stage}
    dl.config_path = str(tmp_path / "config.yml")
    dl.config = {"xy_envelope": dict(env or {})}

    class _NoPause:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    dl.pause_state_updates = lambda: _NoPause()  # type: ignore[method-assign]
    return dl


class _Req:
    def __init__(self, body):
        self._b = body

    async def json(self):
        return self._b


def _switch(dl, enforced: bool):
    resp = asyncio.run(dl.handle_set_envelope_enforced(_Req({"enforced": enforced})))
    return resp.status, json.loads(resp.text)


def _sidecar(tmp_path):
    import yaml

    return (yaml.safe_load((tmp_path / "config.local.yml").read_text()) or {}).get(
        "xy_envelope", {}
    )


def test_the_switch_off_restores_the_controller_and_keeps_gently_on_the_region(tmp_path):
    tiger = _Tiger(held_um=REGION)  # enforced, on the region
    core = _Core(tiger)
    st = _stage(core)
    dl = _dl(st, tmp_path, env={**REGION, "enforced": True})

    status, body = _switch(dl, False)

    assert status == 200, body
    assert "SL X- Y-" in [c for c, _ in core.sent]
    assert body["enforced"] is False
    assert body["x_min"] == -110_000.0, "the payload reports what the controller holds"
    assert body["full_travel"] == {
        "x_min": -110_000.0,
        "x_max": 110_000.0,
        "y_min": -110_000.0,
        "y_max": 110_000.0,
    }
    assert st.x_limits == (REGION["x_min"], REGION["x_max"]), "Gently is still held to the region"
    saved = _sidecar(tmp_path)
    assert saved["enforced"] is False and saved["x_min"] == REGION["x_min"], "the region survives"
    assert saved["controller_defaults"]["x_max"] == 110_000.0


def test_enforced_means_the_controller_holds_the_region(tmp_path):
    """Not "differs from the constants" — which called a software-only
    region "enforced" and a controller at its own defaults "off"."""
    tiger = _Tiger(
        held_um={"x_min": -110_000, "x_max": 110_000, "y_min": -110_000, "y_max": 110_000}
    )
    st = _stage(_Core(tiger))
    dl = _dl(st, tmp_path, env={**REGION, "enforced": False})
    # Gently is bound to the region in software; the controller is wide open.
    st.set_software_limits(REGION["x_min"], REGION["x_max"], REGION["y_min"], REGION["y_max"])

    payload = dl._envelope_payload(st)
    assert payload["enforced"] is False, "a software-only region is not an enforced one"
    assert payload["software"]["x_min"] == REGION["x_min"]

    status, body = _switch(dl, True)
    assert status == 200, body
    assert body["enforced"] is True, "now the controller holds it"
    assert body["x_min"] == REGION["x_min"]


def test_boot_leaves_the_controller_alone_when_off(tmp_path):
    """Whatever it holds, someone put there — an earlier off, or a hand in
    Micro-Manager. A boot that rewrote it is the bug nobody connects to us."""
    someone_elses = {"x_min": -5000.0, "x_max": 5000.0, "y_min": -4000.0, "y_max": 4000.0}
    core = _Core(_Tiger(held_um=someone_elses))
    st = _stage(core)
    dl = _dl(st, tmp_path, env={"enforced": False})

    dl._settle_firmware_limits_at_boot(st, {"enforced": False}, INSET)

    assert not any("-" in c.split(" ", 1)[1] for c, _ in core.sent), (
        "boot restored defaults over someone's limits"
    )
    assert not any("=" in c for c, _ in core.sent), "boot wrote a box"
    assert st.read_firmware_limits() == someone_elses


def test_boot_cleans_up_the_inset_box_it_used_to_write_once(tmp_path):
    """The one exception: our own leftover, from when off wrote the constants."""
    core = _Core(_Tiger(held_um=INSET))
    st = _stage(core)
    dl = _dl(st, tmp_path, env={"enforced": False})

    dl._settle_firmware_limits_at_boot(st, {"enforced": False}, INSET)

    assert "SL X- Y-" in [c for c, _ in core.sent]
    assert _sidecar(tmp_path)["controller_defaults"]["x_min"] == -110_000.0

    # and having done so, a second boot has nothing to do
    core.sent.clear()
    dl._settle_firmware_limits_at_boot(st, {"enforced": False}, INSET)
    assert not any("-" in c.split(" ", 1)[1] for c, _ in core.sent)


def test_the_constants_are_never_written_as_off(tmp_path):
    """The bug, stated as a property: nothing that means "off" writes them."""
    tiger = _Tiger(held_um=REGION)
    core = _Core(tiger)
    dl = _dl(_stage(core), tmp_path, env={**REGION, "enforced": True})
    _switch(dl, False)
    for c, _ in core.sent:
        for v in INSET.values():
            assert f"={v / 1000:.4f}" not in c and f"={v / 1000}" not in c, c


def test_a_region_applied_this_session_can_be_enforced_this_session(tmp_path):
    """Found while fixing the payload: the sidecar write never refreshed the
    in-memory config, so after applying a region the switch still saw the
    value from boot — no region — and answered 409 until a restart."""
    core = _Core(
        _Tiger(held_um={"x_min": -110_000, "x_max": 110_000, "y_min": -110_000, "y_max": 110_000})
    )
    st = _stage(core)
    dl = _dl(st, tmp_path, env={"enforced": False})

    resp = asyncio.run(dl.handle_set_envelope(_Req(dict(REGION))))
    assert resp.status == 200, resp.text

    status, body = _switch(dl, True)
    assert status == 200, body
    assert body["enforced"] is True
    assert body["x_min"] == REGION["x_min"], "the controller now holds the region just walked"


def test_a_controller_that_refuses_the_cleanup_still_boots(tmp_path):
    """Firmware older than 2.8 does not know `SL X-`. The rig comes up anyway,
    holding what it held, and the log says why."""
    tiger = _Tiger(held_um=INSET)
    tiger.reject.add("SL X- Y-")
    core = _Core(tiger)
    st = _stage(core)
    dl = _dl(st, tmp_path, env={"enforced": False})

    dl._settle_firmware_limits_at_boot(st, {"enforced": False}, INSET)  # must not raise

    assert st.read_firmware_limits() == INSET, "a refused cleanup changed something"
