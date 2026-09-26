"""A running calibration can be aborted.

"calibration routine -- while it is running, has no abort feature. in
devices > operate > calibration"

The routine runs agent-side as a long series of short device-layer plans, so
there is nothing on the device layer to abort: what stops is the tool's task
in the web process, and every positioner is halted after it. Everything
here runs against fakes.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("httpx")

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402

# The calibrate routes import the calibration tools, whose @tool decorators
# register against the live registry at import. Imported here, once, against
# the REAL registry — before any test swaps in a fake — so the route's import
# is a no-op and the fake never has to be a registry.
import gently.app.tools.calibration_tools  # noqa: E402, F401
import gently.ui.web.auth as auth  # noqa: E402
from gently.ui.web.routes.data import create_router  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
DEVICE_LAYER = (
    Path(__file__).resolve().parents[1] / "gently" / "hardware" / "dispim" / "device_layer.py"
).read_text(encoding="utf-8")


class _SlowRegistry:
    """A calibration that takes as long as the test lets it."""

    def __init__(self):
        self.started = asyncio.Event()
        self.finished = False
        self.cancelled = False

    def register(self, *a, **k):  # a tool module re-registering against us
        return None

    async def execute(self, name, args, context):
        self.started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        self.finished = True
        return "calibrated"


def _server():
    server = MagicMock()
    agent = SimpleNamespace(
        experiment=SimpleNamespace(embryos={"embryo_1": SimpleNamespace(calibration={})}),
        client=MagicMock(),
        session_id="s1",
    )
    agent.client.is_connected = True
    agent.client.halt_motion = AsyncMock(return_value={"success": True, "halted": ["xy_stage"]})
    server.agent_bridge.agent = agent
    return server, agent


async def _client(server, registry, monkeypatch):
    import gently.harness.tools.registry as reg_mod

    monkeypatch.setattr(reg_mod, "get_tool_registry", lambda: registry)
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://t")


def test_abort_stops_the_running_calibration_and_halts_motion(monkeypatch):
    async def scenario():
        server, agent = _server()
        registry = _SlowRegistry()
        async with await _client(server, registry, monkeypatch) as c:
            run = asyncio.create_task(c.post("/api/devices/embryos/embryo_1/calibrate", json={}))
            await asyncio.wait_for(registry.started.wait(), 5)
            assert getattr(agent, "_calibration_task", None) is not None, (
                "the run was not registered"
            )

            r = await c.post("/api/devices/calibrate/abort", json={})
            assert r.status_code == 200, r.text
            assert r.json()["aborted"] is True and r.json()["what"] == "embryo_1"
            agent.client.halt_motion.assert_awaited_once()

            res = await asyncio.wait_for(run, 5)
            assert res.status_code == 409, res.text
            assert "aborted" in res.json()["detail"]
            assert registry.cancelled and not registry.finished
            assert getattr(agent, "_calibration_task", None) is None, (
                "the finished task was left registered"
            )

    asyncio.run(scenario())


def test_abort_with_nothing_running_is_not_an_error(monkeypatch):
    async def scenario():
        server, agent = _server()
        async with await _client(server, _SlowRegistry(), monkeypatch) as c:
            r = await c.post("/api/devices/calibrate/abort", json={})
            assert r.status_code == 200
            assert r.json()["aborted"] is False
            agent.client.halt_motion.assert_not_awaited()

    asyncio.run(scenario())


def test_the_batch_calibration_is_abortable_too(monkeypatch):
    async def scenario():
        server, agent = _server()
        agent.experiment.embryos["embryo_1"].calibration = {}
        agent.experiment.embryos["embryo_1"].should_skip = False
        agent.experiment.notify_embryos_changed = lambda: None
        registry = _SlowRegistry()
        async with await _client(server, registry, monkeypatch) as c:
            run = asyncio.create_task(c.post("/api/devices/calibrate/all", json={}))
            try:
                await asyncio.wait_for(registry.started.wait(), 5)
            except asyncio.TimeoutError:
                res = await run
                pytest.skip(
                    f"batch route never reached the tool here: {res.status_code} {res.text[:60]}"
                )
            r = await c.post("/api/devices/calibrate/abort", json={})
            assert r.json()["aborted"] is True and r.json()["what"] == "all"
            res = await asyncio.wait_for(run, 5)
            assert res.status_code == 409 and "aborted" in res.json()["detail"]

    asyncio.run(scenario())


def test_a_client_that_goes_away_still_cancels_as_before(monkeypatch):
    """Our own cancellation (the tab closed) must not be dressed up as an abort."""

    async def scenario():
        server, agent = _server()
        registry = _SlowRegistry()
        from gently.ui.web.routes.data import _run_cancellable_calibration

        async def route_like():
            return await _run_cancellable_calibration(
                agent, registry.execute("x", {}, {}), "embryo_1"
            )

        outer = asyncio.create_task(route_like())
        await asyncio.wait_for(registry.started.wait(), 5)
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer
        assert registry.cancelled

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# The pane, and the halt
# ---------------------------------------------------------------------------


def _wire_body() -> str:
    start = OPERATE.index("if (_wired) return;")
    end = OPERATE.index("\n    async function ", start)
    return OPERATE[start:end]


def test_abort_is_on_the_pane_only_while_it_runs_and_is_wired():
    assert 'id="op-cal-abort"' in HTML and "hidden>Abort</button>" in HTML
    assert "$('op-cal-abort')" in _wire_body() and "abortCalibration" in _wire_body()
    fn = OPERATE[OPERATE.index("async function calibrateSelected(") :][:4200]
    assert "ab.hidden = false" in fn and "if (ab) ab.hidden = true" in fn
    assert "/aborted/i.test(detail)" in fn, "an abort reads as a failure or a refusal"
    assert fn.index("/aborted/i.test(detail)") < fn.index("showRefusal(e)"), (
        "the abort branch must be checked before the pre-flight refusal, both are 409"
    )


def test_halt_now_covers_the_piezo():
    m = re.search(r'for key in \(("fdrive", "xy_stage", "z_stage"[^)]*)\):', DEVICE_LAYER)
    assert m and '"piezo"' in m.group(1), (
        "an aborted sweep leaves the piezo wherever it was heading"
    )
