"""Two things an audit left open.

Every time on disk is the PC's local time with no zone. When the clocks go
back an hour, at two in the morning, a run's next round is suddenly an hour
and five minutes away, and two stacks taken in the repeated hour cannot be
told apart or timed against each other.

488 is bounded at 6 %. The other laser lines may stand at anything, and a
line the plan gives no power runs at whatever it was last set to by hand.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import yaml

from gently.app.orchestration import timelapse
from gently.app.orchestration.timelapse import TimelapseOrchestrator
from gently.core.file_store import FileStore, _in_utc

REPO = Path(__file__).resolve().parents[1]


def _run(powers=None):
    orch = TimelapseOrchestrator.__new__(TimelapseOrchestrator)
    orch._clock_seen = None
    orch._bf_next_due_at = None
    orch._embryo_states = {}
    orch._powers_at_start = {}
    orch._laser_config = None

    class Client:
        async def get_laser_power(self, wl):
            return {"success": True, "pct": (powers or {}).get(wl)}

    orch.client = Client()
    return orch


def test_the_clock_going_back_does_not_put_an_hour_into_the_cadence():
    orch = _run()
    two = datetime(2026, 11, 1, 1, 59, 0)
    due = two + timedelta(minutes=5)
    a = SimpleNamespace(next_due_at=due)
    b = SimpleNamespace(next_due_at=None)  # not scheduled yet: left alone
    orch._embryo_states = {"a": a, "b": b}
    orch._bf_next_due_at = due

    orch._mind_the_clock(two)
    orch._mind_the_clock(two + timedelta(seconds=30))  # an ordinary tick
    assert a.next_due_at == due

    # 02:00 becomes 01:00. The round that was 4 min 30 s away still is.
    after = two + timedelta(seconds=30) - timedelta(hours=1)
    orch._mind_the_clock(after)
    assert a.next_due_at - after == timedelta(minutes=4, seconds=30)
    assert orch._bf_next_due_at - after == timedelta(minutes=4, seconds=30)
    assert b.next_due_at is None

    # Forward needs nothing: what is overdue is imaged and the cadence goes on.
    orch._mind_the_clock(after + timedelta(hours=1))
    assert a.next_due_at - after == timedelta(minutes=4, seconds=30)
    # The round picker is where it is asked.
    src = (REPO / "gently/app/orchestration/timelapse.py").read_text(encoding="utf-8")
    assert "now = datetime.now()\n        self._mind_the_clock(now)" in src


def test_a_stack_is_timed_in_utc_as_well(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("s1", name="night")
    store.register_embryo("s1", "embryo_1")
    vol = np.zeros((2, 4, 4), dtype=np.uint16)
    local = "2026-11-15T09:14:11.400000"
    path = store.put_volume("s1", "embryo_1", 0, vol, acquired_at=local)
    meta = yaml.safe_load(Path(str(path).replace(".tif", ".meta.yaml")).read_text())
    # The local time is as it was; the same moment is beside it with its Z.
    assert str(meta["acquired_at"]) == local
    assert meta["acquired_at_utc"] == _in_utc(local) and meta["acquired_at_utc"].endswith("Z")
    utc = datetime.fromisoformat(meta["acquired_at_utc"].replace("Z", "+00:00"))
    assert utc.astimezone().replace(tzinfo=None) == datetime.fromisoformat(local)
    # And in the export's table of volumes.
    export = (REPO / "gently/core/export.py").read_text(encoding="utf-8")
    assert '"acquired_at_utc": v.get("acquired_at_utc") or "",' in export


def test_a_run_is_not_started_on_a_power_nobody_chose():
    limit = timelapse.UNPLANNED_POWER_AT_MOST_PCT
    unset = SimpleNamespace(
        laser_power_561_pct=None, laser_power_405_pct=None, laser_power_637_pct=None
    )
    orch = _run({561: 80.0, 405: 0.0, 637: 50.0})

    # 561 is on in this preset and nobody gave it a power: refused, and named.
    why = asyncio.run(orch.left_high_by_hand("488 and 561", [unset]))
    assert why and "561 nm is at 80 %" in why and "637" not in why
    assert f"{limit:g} % at most" in why
    # No preset is the plan's default, which turns 561 on too.
    assert asyncio.run(orch.left_high_by_hand(None, [unset]))
    # A line the preset does not turn on is nobody's business here.
    assert asyncio.run(orch.left_high_by_hand("488 only", [unset])) is None
    # A power the plan states is the operator's choice.
    planned = SimpleNamespace(
        laser_power_561_pct=80.0, laser_power_405_pct=None, laser_power_637_pct=None
    )
    assert asyncio.run(orch.left_high_by_hand("488 and 561", [planned])) is None
    # At or under the limit it starts, and that power is then held for the run.
    orch = _run({561: limit})
    assert asyncio.run(orch.left_high_by_hand("488 and 561", [unset])) is None
    # The page's start asks before a volume is taken.
    route = (REPO / "gently/ui/web/routes/data.py").read_text(encoding="utf-8")
    start = route[route.index("    async def timelapse_start(") :]
    assert start.index('"left_high_by_hand"') < start.index("await orchestrator.start(")
