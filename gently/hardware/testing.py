"""Testing helpers for hardware-dependent code.

The helpers in this module are intentionally small and dependency-free so tests
can exercise agent/tool behavior without importing Micro-Manager or talking to
physical devices.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, Iterable, List, Mapping, Optional, Tuple


@dataclass(frozen=True)
class HardwareCondition:
    """Result of checking whether a hardware capability is available."""

    name: str
    available: bool
    details: Mapping[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def require(self) -> None:
        """Raise an AssertionError when the condition is not available."""
        if not self.available:
            message = f"Hardware condition unavailable: {self.name}"
            if self.error:
                message = f"{message}: {self.error}"
            raise AssertionError(message)


class MockQueueServerClient:
    """Scriptable async fake for tests that normally need a device layer.

    It implements the common methods used by Gently tools and records every
    call. Tests can use :meth:`script_response` or :meth:`fail` to model device
    success and failure paths deterministically.
    """

    def __init__(
        self,
        *,
        stage_position: Tuple[float, float] = (0.0, 0.0),
        piezo_position: float = 0.0,
        has_sam: bool = True,
        device_state: Optional[Mapping[str, Any]] = None,
    ):
        self.stage_position = stage_position
        self.piezo_position = piezo_position
        self.has_sam = has_sam
        self.is_connected = False
        self.calls: List[Dict[str, Any]] = []
        self._responses: Dict[str, Deque[Any]] = defaultdict(deque)
        self._failures: Dict[str, Exception] = {}
        self._stream_states: Deque[Mapping[str, Any]] = deque()
        self._device_state = dict(device_state or {})

    def script_response(self, method: str, *responses: Any) -> None:
        """Queue one or more responses for a method name."""
        self._responses[method].extend(responses)

    def script_stream(self, *states: Mapping[str, Any]) -> None:
        """Queue device-state events for :meth:`stream_device_states`."""
        self._stream_states.extend(states)

    def fail(self, method: str, error: Exception) -> None:
        """Make a method raise ``error`` until the failure is cleared."""
        self._failures[method] = error

    def clear_failure(self, method: str) -> None:
        self._failures.pop(method, None)

    def recorded_calls(self, method: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all recorded calls, optionally filtered by method."""
        if method is None:
            return list(self.calls)
        return [call for call in self.calls if call["method"] == method]

    def _record(self, method: str, **payload: Any) -> None:
        self.calls.append({"method": method, **payload})

    def _next_response(self, method: str, default: Any) -> Any:
        if method in self._failures:
            raise self._failures[method]
        if self._responses[method]:
            response = self._responses[method].popleft()
            if isinstance(response, Exception):
                raise response
            if callable(response):
                return response()
            return response
        return default

    async def connect(self) -> bool:
        self._record("connect")
        result = self._next_response("connect", True)
        self.is_connected = bool(result)
        return self.is_connected

    async def disconnect(self) -> None:
        self._record("disconnect")
        self.is_connected = False

    async def get_stage_position(self) -> Tuple[float, float]:
        self._record("get_stage_position")
        return self._next_response("get_stage_position", self.stage_position)

    async def move_to_position(self, x: float, y: float) -> Dict[str, Any]:
        self._record("move_to_position", x=x, y=y)
        self.stage_position = (float(x), float(y))
        return self._next_response(
            "move_to_position",
            {"success": True, "x": self.stage_position[0], "y": self.stage_position[1]},
        )

    async def get_piezo_position(self) -> float:
        self._record("get_piezo_position")
        return self._next_response("get_piezo_position", self.piezo_position)

    async def get_device_state(self, refresh: bool = False) -> Dict[str, Any]:
        self._record("get_device_state", refresh=refresh)
        state = {
            "available": True,
            "positions": {
                "stage": {"x": self.stage_position[0], "y": self.stage_position[1]},
                "piezo": self.piezo_position,
            },
            **self._device_state,
        }
        return self._next_response("get_device_state", state)

    async def stream_device_states(self, timeout: Optional[float] = None) -> AsyncIterator[Dict[str, Any]]:
        self._record("stream_device_states", timeout=timeout)
        if not self._stream_states:
            yield await self.get_device_state(refresh=False)
            return
        while self._stream_states:
            yield dict(self._stream_states.popleft())

    async def capture_bottom_image(self, exposure_ms: float = 10.0) -> Dict[str, Any]:
        self._record("capture_bottom_image", exposure_ms=exposure_ms)
        return self._next_response(
            "capture_bottom_image",
            {"success": True, "image": [[0]], "exposure_ms": exposure_ms},
        )

    async def capture_for_marking(self, exposure_ms: float = 10.0) -> Dict[str, Any]:
        self._record("capture_for_marking", exposure_ms=exposure_ms)
        return self._next_response(
            "capture_for_marking",
            {"success": True, "image": [[0]], "stage_position": self.stage_position},
        )

    async def capture_lightsheet_image(self, **kwargs: Any) -> Dict[str, Any]:
        self._record("capture_lightsheet_image", **kwargs)
        return self._next_response(
            "capture_lightsheet_image",
            {"success": True, "image": [[0]], "shape": (1, 1), **kwargs},
        )

    async def acquire_volume(self, **kwargs: Any) -> Dict[str, Any]:
        self._record("acquire_volume", **kwargs)
        return self._next_response(
            "acquire_volume",
            {"success": True, "volume": None, "shape": (0,), **kwargs},
        )

    async def detect_embryos(self, **kwargs: Any) -> Dict[str, Any]:
        self._record("detect_embryos", **kwargs)
        return self._next_response("detect_embryos", {"success": True, "embryos": []})

    async def set_led(self, state: str) -> Dict[str, Any]:
        self._record("set_led", state=state)
        return self._next_response("set_led", {"success": True, "state": state})

    async def get_led_status(self) -> Dict[str, Any]:
        self._record("get_led_status")
        return self._next_response("get_led_status", {"state": "unknown"})

    async def set_laser_power(self, wavelength: int, pct: float) -> Dict[str, Any]:
        self._record("set_laser_power", wavelength=wavelength, pct=pct)
        return self._next_response(
            "set_laser_power",
            {"success": True, "wavelength": wavelength, "power_pct": pct},
        )

    async def get_laser_power(self, wavelength: int) -> Dict[str, Any]:
        self._record("get_laser_power", wavelength=wavelength)
        return self._next_response(
            "get_laser_power",
            {"wavelength": wavelength, "power_pct": 0.0},
        )

    async def set_temperature(self, target_c: float) -> Dict[str, Any]:
        self._record("set_temperature", target_c=target_c)
        return self._next_response("set_temperature", {"success": True, "target_c": target_c})

    async def get_temperature(self) -> Dict[str, Any]:
        self._record("get_temperature")
        return self._next_response("get_temperature", {"current_c": None, "target_c": None})


def summarize_conditions(conditions: Iterable[HardwareCondition]) -> Dict[str, bool]:
    """Return a compact availability map for a set of hardware conditions."""
    return {condition.name: condition.available for condition in conditions}
