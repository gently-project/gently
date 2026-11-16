"""A beam armed for a live view is disarmed when the view ends, and a run
disarms both before its first round."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from gently.app.orchestration.timelapse import TimelapseOrchestrator
from gently.hardware.dispim.device_layer import DeviceLayerServer

LAYER = (
    Path(__file__).resolve().parents[1] / "gently" / "hardware" / "dispim" / "device_layer.py"
).read_text(encoding="utf-8")


def _layer(armed: dict[str, bool]) -> SimpleNamespace:
    devices = {"scanner": MagicMock(), "scanner_b": MagicMock()}
    return SimpleNamespace(
        devices=devices,
        _BEAM_SIDES=DeviceLayerServer._BEAM_SIDES,
        _read_beam=lambda: dict(armed),
    )


def test_only_the_beams_that_are_armed_are_written_to() -> None:
    layer = _layer({"a": True, "b": False})
    assert DeviceLayerServer._beams_off(layer, "test") == ["a"]  # type: ignore[arg-type]
    layer.devices["scanner"].enable_beam.assert_called_once_with(False)
    layer.devices["scanner_b"].enable_beam.assert_not_called()


def test_a_beam_that_will_not_read_does_not_raise() -> None:
    layer = _layer({})
    layer._read_beam = MagicMock(side_effect=RuntimeError("controller busy"))
    assert DeviceLayerServer._beams_off(layer, "test") == []  # type: ignore[arg-type]


def test_the_view_ending_disarms_the_beams() -> None:
    streamer = LAYER[LAYER.index("    async def _lightsheet_streamer(self):") :]
    streamer = streamer[: streamer.index("    async def _broadcast_lightsheet(")]
    end = streamer[streamer.index("        finally:") :]
    assert 'self._beams_off, "the live view ended"' in end
    # After the camera's sequence is stopped: the view is over, then the light.
    assert end.index("_stop_lightsheet_sequence_sync") < end.index("_beams_off")


def test_a_run_disarms_both_beams_before_its_first_round() -> None:
    client = MagicMock()
    client.set_beam = AsyncMock(return_value={"success": True})
    orch = SimpleNamespace(client=client)
    asyncio.run(TimelapseOrchestrator._beams_off_at_start(orch))  # type: ignore[arg-type]
    client.set_beam.assert_awaited_once_with(False, "both")


def test_a_client_that_cannot_disarm_does_not_stop_the_run() -> None:
    client = MagicMock()
    client.set_beam = AsyncMock(side_effect=RuntimeError("no scanner"))
    asyncio.run(TimelapseOrchestrator._beams_off_at_start(SimpleNamespace(client=client)))  # type: ignore[arg-type]
