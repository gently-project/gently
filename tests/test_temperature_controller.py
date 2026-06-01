import json
import os
import time
from pathlib import Path

import pytest

from gently.hardware.temperature import (
    TemperatureController,
    _MockBackend,
    create_temperature_controller,
)


def test_nonblocking_setpoint_updates_reported_setpoint():
    dev = TemperatureController(_MockBackend(), name="temperature")

    dev.enable(True)
    dev.setpoint(21.5)
    readback = dev.read()

    assert readback["temperature_setpoint"]["value"] == 21.5
    assert readback["temperature"]["value"] == 21.5


def test_nonblocking_setpoint_validates_range():
    dev = TemperatureController(_MockBackend(), name="temperature")

    with pytest.raises(ValueError, match="outside"):
        dev.setpoint(120.0)


def _mqtt_digital_twin_config():
    raw = os.getenv("GENTLY_MQTT_THERMOSTAT_CONFIG")
    if not raw:
        pytest.skip(
            "set GENTLY_MQTT_THERMOSTAT_CONFIG to a JSON config or config path "
            "to run the MQTT thermostat digital-twin test"
        )

    candidate = Path(raw)
    if candidate.exists():
        cfg = json.loads(candidate.read_text(encoding="utf-8"))
    else:
        cfg = json.loads(raw)
    cfg.setdefault("backend", "mqtt")
    cfg.setdefault("name", "temperature")
    return cfg


def test_mqtt_digital_twin_reports_commanded_setpoint():
    """Opt-in check for Roland's MQTT thermostat digital twin.

    The test exercises the same non-blocking command path used by
    `/api/temperature/set`, but only runs when broker/config details are
    supplied explicitly.
    """
    cfg = _mqtt_digital_twin_config()
    target = float(os.getenv("GENTLY_MQTT_THERMOSTAT_TARGET_C", "21.5"))
    timeout_s = float(os.getenv("GENTLY_MQTT_THERMOSTAT_TIMEOUT_S", "10"))
    tolerance_c = float(os.getenv("GENTLY_MQTT_THERMOSTAT_TOLERANCE_C", "0.25"))

    try:
        dev = create_temperature_controller(cfg)
    except ImportError as exc:
        pytest.skip(f"MQTT thermostat SDK is unavailable: {exc}")

    try:
        dev.enable(True)
        dev.setpoint(target)
        readback = dev.read()

        assert readback["temperature_setpoint"]["value"] == pytest.approx(target)

        deadline = time.monotonic() + timeout_s
        last = readback
        while time.monotonic() < deadline:
            temp = last["temperature"]["value"]
            state = str(last["temperature_state"]["value"])
            if temp is not None and abs(float(temp) - target) <= tolerance_c:
                return
            if "LOCKED" in state.upper():
                return
            time.sleep(0.5)
            last = dev.read()

        pytest.fail(
            "MQTT thermostat digital twin did not converge or report lock "
            f"within {timeout_s:.1f}s; last read={last!r}"
        )
    finally:
        dev.close()
