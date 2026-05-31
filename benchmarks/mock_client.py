"""Mock hardware client for copilot benchmark runs."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Mapping, Optional, Tuple


class MockQueueServerClient:
    """Scriptable fake for benchmark scenarios.

    The class mirrors the async shape of the diSPIM queue/server client methods
    used by tools. It records calls and lets benchmark tasks configure success
    responses or failure scenarios without touching physical hardware.
    """

    def __init__(
        self,
        *,
        stage_position: Tuple[float, float] = (0.0, 0.0),
        has_sam: bool = True,
    ):
        self.stage_position = stage_position
        self.has_sam = has_sam
        self.calls: List[Dict[str, Any]] = []
        self._responses: Dict[str, Deque[Any]] = defaultdict(deque)
        self._failures: Dict[str, Exception] = {}

    def script_response(self, method: str, *responses: Any) -> None:
        self._responses[method].extend(responses)

    def fail(self, method: str, error: Exception) -> None:
        self._failures[method] = error

    def clear_failure(self, method: str) -> None:
        self._failures.pop(method, None)

    def reset_calls(self) -> None:
        self.calls.clear()

    def recorded_calls(self, method: Optional[str] = None) -> List[Dict[str, Any]]:
        if method is None:
            return list(self.calls)
        return [call for call in self.calls if call["method"] == method]

    def _record(self, method: str, **payload: Any) -> None:
        self.calls.append({"method": method, **payload})

    def _response(self, method: str, default: Any) -> Any:
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

    async def get_stage_position(self) -> Tuple[float, float]:
        self._record("get_stage_position")
        return self._response("get_stage_position", self.stage_position)

    async def move_to_position(self, x: float, y: float) -> Mapping[str, Any]:
        self._record("move_to_position", x=x, y=y)
        self.stage_position = (float(x), float(y))
        return self._response(
            "move_to_position",
            {"success": True, "x": self.stage_position[0], "y": self.stage_position[1]},
        )

    async def detect_embryos(self, **kwargs: Any) -> Mapping[str, Any]:
        self._record("detect_embryos", **kwargs)
        return self._response("detect_embryos", {"success": True, "embryos": []})

    async def capture_bottom_image(self, **kwargs: Any) -> Mapping[str, Any]:
        self._record("capture_bottom_image", **kwargs)
        return self._response(
            "capture_bottom_image",
            {"success": True, "image": [[0]], "stage_position": self.stage_position},
        )

    async def capture_for_marking(self, **kwargs: Any) -> Mapping[str, Any]:
        self._record("capture_for_marking", **kwargs)
        return self._response(
            "capture_for_marking",
            {"success": True, "image": [[0]], "stage_position": self.stage_position},
        )

    async def acquire_volume(self, **kwargs: Any) -> Mapping[str, Any]:
        self._record("acquire_volume", **kwargs)
        return self._response(
            "acquire_volume",
            {"success": True, "volume": None, "shape": (0,), **kwargs},
        )

    async def capture_lightsheet_image(self, **kwargs: Any) -> Mapping[str, Any]:
        self._record("capture_lightsheet_image", **kwargs)
        return self._response(
            "capture_lightsheet_image",
            {"success": True, "image": [[0]], "shape": (1, 1), **kwargs},
        )
