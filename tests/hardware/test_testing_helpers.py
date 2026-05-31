import pytest

from gently.hardware.testing import (
    HardwareCondition,
    MockQueueServerClient,
    summarize_conditions,
)


pytestmark = pytest.mark.hardware


@pytest.mark.asyncio
async def test_mock_client_records_stage_moves():
    client = MockQueueServerClient(stage_position=(10.0, 20.0))

    await client.move_to_position(1200.5, -25.0)

    assert await client.get_stage_position() == (1200.5, -25.0)
    assert client.recorded_calls("move_to_position") == [
        {"method": "move_to_position", "x": 1200.5, "y": -25.0}
    ]


@pytest.mark.asyncio
async def test_mock_client_scripts_failures():
    client = MockQueueServerClient()
    client.fail("acquire_volume", RuntimeError("camera timeout"))

    with pytest.raises(RuntimeError, match="camera timeout"):
        await client.acquire_volume(num_slices=5)

    assert client.recorded_calls("acquire_volume")[0]["num_slices"] == 5


@pytest.mark.asyncio
async def test_mock_client_streams_scripted_device_states():
    client = MockQueueServerClient()
    client.script_stream(
        {"positions": {"stage": {"x": 1.0, "y": 2.0}}},
        {"positions": {"stage": {"x": 3.0, "y": 4.0}}},
    )

    states = []
    async for state in client.stream_device_states(timeout=0.1):
        states.append(state)

    assert [state["positions"]["stage"]["x"] for state in states] == [1.0, 3.0]
    assert client.recorded_calls("stream_device_states")[0]["timeout"] == 0.1


def test_hardware_condition_require_raises_with_context():
    condition = HardwareCondition(
        name="device-layer",
        available=False,
        error="not reachable",
    )

    with pytest.raises(AssertionError, match="device-layer: not reachable"):
        condition.require()


def test_summarize_conditions_reports_availability():
    conditions = [
        HardwareCondition("stage", True),
        HardwareCondition("camera", False, error="not configured"),
    ]

    assert summarize_conditions(conditions) == {"stage": True, "camera": False}
