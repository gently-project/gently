"""One request fits side A and then side B.

"in the finding the fit there is side A and B separately, but it does not aid
automation ... there should be an option to find both sides fitting." Two
presses with a select turned between them is not something a script or a
batch can lean on. ``side: "both"`` on the calibrate route runs A, then B,
each exactly as it would run alone.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

import gently.app.tools.calibration_tools  # noqa: F401  registered before the stand-in
import gently.ui.web.routes.data as data
from gently.ui.web import auth


def _client(monkeypatch, replies):
    """The route with the calibration tool stood in for: each call is noted
    with its side, and answers from ``replies``."""
    calls: list[dict] = []
    embryo = SimpleNamespace(
        calibration={"slope_um_per_deg": 35.0, "B": {"slope_um_per_deg": 36.0}}
    )
    agent = SimpleNamespace(
        experiment=SimpleNamespace(
            embryos={"embryo_1": embryo}, notify_embryos_changed=lambda: None
        )
    )
    server = MagicMock()
    server.agent_bridge.agent = agent
    rig = MagicMock()
    rig.is_connected = True
    agent.client = rig
    server.agent_bridge.agent.client = rig

    class Registry:
        def register(self, *a, **k):
            return None

        async def execute(self, name, args, context):
            calls.append(dict(args))
            reply = replies[args.get("side", "A")]
            if isinstance(reply, Exception):
                raise reply
            return reply

    import gently.harness.tools.registry as registry

    monkeypatch.setattr(registry, "get_tool_registry", lambda: Registry())

    async def straight(agent_, coro, embryo_id):
        return await coro

    monkeypatch.setattr(data, "_run_cancellable_calibration", straight)
    app = FastAPI()
    app.include_router(data.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app), calls


def test_both_runs_side_a_then_side_b_by_the_scan_routine(monkeypatch):
    c, calls = _client(monkeypatch, {"A": "fit 35.0", "B": "fit 36.0"})
    r = c.post("/api/devices/embryos/embryo_1/calibrate", json={"side": "both", "z_buffer_um": 30})
    assert r.status_code == 200, r.text
    assert [(a["side"], a["method"], a["z_buffer_um"]) for a in calls] == [
        ("A", "scan", 30.0),
        ("B", "scan", 30.0),
    ]
    body = r.json()
    assert body["sides"] == {"A": "fit 35.0", "B": "fit 36.0"}
    assert body["message"] == "side A: fit 35.0 | side B: fit 36.0"
    assert body["calibration"]["B"]["slope_um_per_deg"] == 36.0


def test_one_side_alone_is_as_it_was(monkeypatch):
    c, calls = _client(monkeypatch, {"A": "fit 35.0", "B": "fit 36.0"})
    r = c.post("/api/devices/embryos/embryo_1/calibrate", json={"side": "B", "method": "scan"})
    assert r.status_code == 200 and [a["side"] for a in calls] == ["B"]
    assert "sides" not in r.json()


def test_a_side_that_fails_says_which_and_what_was_kept(monkeypatch):
    from gently.app.tools.calibration_tools import NO_OBJECT_PREFIX

    nothing = f"{NO_OBJECT_PREFIX} for embryo_1: nothing lit clears the floor"
    c, calls = _client(monkeypatch, {"A": "fit 35.0", "B": nothing})
    r = c.post("/api/devices/embryos/embryo_1/calibrate", json={"side": "both"})
    # Still a refusal, with its reason first as for one side.
    assert r.status_code == 409
    assert r.json()["detail"] == f"{nothing} (side B; side A calibrated and kept)"

    # Side A failing stops there: B is not tried on an embryo that is not seen.
    c, calls = _client(monkeypatch, {"A": nothing, "B": "fit 36.0"})
    r = c.post("/api/devices/embryos/embryo_1/calibrate", json={"side": "both"})
    assert r.status_code == 409 and r.json()["detail"].endswith("(side A)")
    assert [a["side"] for a in calls] == ["A"]
