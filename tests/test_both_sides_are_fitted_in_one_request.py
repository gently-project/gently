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

_AGENTS: list = []  # the agent each app was built on, newest last


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
    _AGENTS.append(agent)
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


def _many(monkeypatch, replies, moved_um=0.0):
    """The batch route over two embryos, with alignment stood in for."""
    c, calls = _client(monkeypatch, replies)
    aligned: list[str] = []

    async def fake_align(client, embryo, move=True):
        aligned.append("x")
        return {"aligned": True, "moved_um": moved_um, "gap_um": 0.4, "position": {"x": 1, "y": 2}}

    import gently.app.ab_align as ab_align
    import gently.app.tools.calibration_tools as tools

    monkeypatch.setattr(ab_align, "align_embryo", fake_align)
    monkeypatch.setattr(tools, "persist_calibration", lambda agent, embryo: True)
    return c, calls, aligned


def test_several_embryos_are_walked_in_the_order_asked_on_both_sides(monkeypatch):
    c, calls, aligned = _many(monkeypatch, {"A": "fit", "B": "fit"})
    r = c.post(
        "/api/devices/calibrate/all",
        json={"embryo_ids": ["embryo_1"], "side": "both", "z_buffer_um": 30},
    )
    assert r.status_code == 200, r.text
    assert [(a["embryo_id"], a["side"], a["method"]) for a in calls] == [
        ("embryo_1", "A", "scan"),
        ("embryo_1", "B", "scan"),
    ]
    body = r.json()
    assert (
        body["calibrated"] == ["embryo_1"] and body["failed"] == [] and body["sides"] == ["A", "B"]
    )
    assert aligned == [] and body["aligned"] == {}
    # The fits as they now stand come back with the reply.
    assert body["calibrations"]["embryo_1"]["B"]["slope_um_per_deg"] == 36.0


def test_aligning_the_views_is_part_of_the_walk_and_a_moved_embryo_is_fitted_again(monkeypatch):
    c, calls, aligned = _many(monkeypatch, {"A": "fit", "B": "fit"}, moved_um=12.0)
    r = c.post(
        "/api/devices/calibrate/all",
        json={"embryo_ids": ["embryo_1"], "side": "both", "align": True},
    )
    body = r.json()
    assert r.status_code == 200 and aligned == ["x"]
    # Fitted, aligned, and fitted again where the stage moved for it.
    assert [a["side"] for a in calls] == ["A", "B", "A", "B"]
    assert body["aligned"]["embryo_1"]["moved_um"] == 12.0

    # Nothing moved: the fit already is of where the embryo is.
    c, calls, aligned = _many(monkeypatch, {"A": "fit", "B": "fit"}, moved_um=0.0)
    c.post(
        "/api/devices/calibrate/all",
        json={"embryo_ids": ["embryo_1"], "side": "both", "align": True},
    )
    assert [a["side"] for a in calls] == ["A", "B"]


def test_aligning_needs_both_sides_and_an_unknown_embryo_is_refused(monkeypatch):
    c, calls, _ = _many(monkeypatch, {"A": "fit", "B": "fit"})
    r = c.post("/api/devices/calibrate/all", json={"embryo_ids": ["embryo_1"], "align": True})
    assert r.status_code == 400 and "both" in r.json()["detail"]
    r = c.post("/api/devices/calibrate/all", json={"embryo_ids": ["embryo_9"]})
    assert r.status_code == 404 and calls == []


def test_nothing_is_calibrated_or_aligned_under_a_run(monkeypatch):
    c, calls, _ = _many(monkeypatch, {"A": "fit", "B": "fit"})
    going = SimpleNamespace(_status=SimpleNamespace(value="running"))
    monkeypatch.setattr(_AGENTS[-1], "timelapse_orchestrator", going, raising=False)
    for url, body in (
        ("/api/devices/embryos/embryo_1/calibrate", {}),
        ("/api/devices/calibrate/all", {"embryo_ids": ["embryo_1"]}),
        ("/api/devices/embryos/embryo_1/align_ab", {}),
    ):
        r = c.post(url, json=body)
        assert r.status_code == 409 and "A run is going" in r.json()["detail"], url
    assert calls == []
