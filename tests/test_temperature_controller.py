import pytest

from gently.hardware.temperature import TemperatureController, _MockBackend


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
