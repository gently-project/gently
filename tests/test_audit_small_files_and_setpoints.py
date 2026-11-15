"""The rest of an audit's findings: small things that lose a little, rarely.

- A note rewritten at the same size read back as it was before.
- Two changes to one small file at once, and one was written over.
- A laser line the plan gave no power ran at whatever was last set by hand.
- The water could be set to 73 for 37.
- An id already in use was used again.
- The inbox read every note on the event loop.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("aiohttp")

from gently.core import file_store as core_store  # noqa: E402
from gently.core.file_store import FileStore  # noqa: E402
from gently.harness.memory.file_store import FileContextStore  # noqa: E402
from gently.harness.memory.notebook import Note, NoteKind, NoteStatus  # noqa: E402
from gently.harness.session.manager import SessionManager  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


def test_a_note_rewritten_at_the_same_size_reads_as_it_now_is(tmp_path):
    cs = FileContextStore(tmp_path / "agent")
    nid = cs.notebook.write_note(Note(id="", kind=NoteKind.FINDING, body="hatching is faster"))
    for status in (NoteStatus.PROPOSED, NoteStatus.ANSWERED, NoteStatus.PROPOSED) * 6:
        note = cs.notebook.get_note(nid)
        note.status = status  # "proposed" and "answered" are the same length
        cs.notebook.write_note(note)
        assert cs.notebook.get_note(nid).status == status


def test_two_changes_to_one_small_file_both_land(tmp_path):
    store = FileStore(tmp_path)
    store.create_session("s1", name="night")
    people = [f"person{i}" for i in range(24)]
    threads = [threading.Thread(target=store.add_session_operator, args=("s1", p)) for p in people]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(store.get_session("s1").get("operators") or []) == sorted(people)
    # The lock is one, re-entrant, and on the writers named.
    src = Path(core_store.__file__).read_text(encoding="utf-8")
    for name in ("touch_session", "set_session_tags", "_write_links", "add_session_operator"):
        assert f"    @one_writer\n    def {name}(" in src, name


def test_a_run_holds_each_line_at_the_power_it_began_with():
    from gently.app.orchestration.timelapse import TimelapseOrchestrator

    orch = TimelapseOrchestrator.__new__(TimelapseOrchestrator)
    orch._laser_config = None
    orch._powers_at_start = {}

    class Client:
        async def get_laser_power(self, wl):
            return {"success": True, "wavelength": wl, "pct": {561: 80.0, 405: 0.0}.get(wl)}

    orch.client = Client()
    asyncio.run(orch._note_powers_at_start())
    assert orch._powers_at_start == {561: 80.0, 405: 0.0}
    plain = SimpleNamespace(laser_power_561_pct=None, laser_power_405_pct=None)
    assert orch._volume_lasers(plain) == {"laser_power_561_pct": 80.0, "laser_power_405_pct": 0.0}
    # The plan's own number still wins.
    planned = SimpleNamespace(laser_power_561_pct=4.0, laser_power_405_pct=None)
    assert orch._volume_lasers(planned)["laser_power_561_pct"] == 4.0
    run = (REPO / "gently/app/orchestration/timelapse.py").read_text(encoding="utf-8")
    assert "await self._note_powers_at_start()\n            while not self._stop_requested:" in run


def test_the_water_is_not_set_outside_what_a_sample_survives():
    from gently.hardware.dispim import device_layer

    assert device_layer.TEMPERATURE_SETPOINT_C == (4.0, 40.0)
    dl = device_layer.DeviceLayerServer.__new__(device_layer.DeviceLayerServer)
    temp = MagicMock()
    dl.devices = {"temperature": temp}

    def ask(target):
        async def body():
            return {"target_c": target}

        resp = asyncio.run(dl.handle_set_temperature(SimpleNamespace(json=body)))
        return json.loads(resp.text)

    assert ask(73)["success"] is False and "outside [4.0, 40.0]" in ask(73)["error"]
    assert ask(-1)["success"] is False
    temp.method_calls.clear()
    assert "outside" not in json.dumps(ask(25))


def test_an_id_in_use_is_not_used_again(tmp_path, monkeypatch):
    import uuid

    store = FileStore(tmp_path)
    store.create_session("aaaaaaaa", name="the first")
    ids = iter(["aaaaaaaa-0000", "bbbbbbbb-0000"])
    monkeypatch.setattr(uuid, "uuid4", lambda: next(ids))
    sessions = SessionManager(store=store, storage_path=tmp_path)
    sessions.create_session()
    assert sessions.session_id == "bbbbbbbb"
    assert store.get_session("aaaaaaaa")["name"] == "the first"

    cs = FileContextStore(tmp_path / "agent")
    ids = iter(["cccccccc-0", "cccccccc-0", "dddddddd-0"])
    first = cs.notebook.write_note(Note(id="", kind=NoteKind.OBSERVATION, body="one"))
    second = cs.notebook.write_note(Note(id="", kind=NoteKind.OBSERVATION, body="two"))
    assert (first, second) == ("cccccccc", "dddddddd")
    assert cs.notebook.get_note(first).body == "one"


def test_the_inbox_is_built_off_the_event_loop():
    src = (REPO / "gently/ui/web/routes/inbox.py").read_text(encoding="utf-8")
    assert src.count("await asyncio.to_thread(inbox_for, store, cs, me)") == 2
    assert "@one_writer\ndef mark_seen(" in src


def test_the_page_and_the_device_layer_bound_the_water_by_one_number():
    """The page's route kept its own 0 to 99.9 after the device layer was
    bounded, and the rig menu's Apply sent a field the route does not read:
    it had never set the water."""
    from gently import settings as settings_module
    from gently.hardware.dispim import device_layer

    assert device_layer.TEMPERATURE_SETPOINT_C is settings_module.WATER_SETPOINT_C
    route = (REPO / "gently/ui/web/routes/data.py").read_text(encoding="utf-8")
    assert (
        "lo, hi = WATER_SETPOINT_C" in route
        and "99.9" not in route[route.index('"/api/devices/temperature/set"') :][:1200]
    )
    menu = (REPO / "gently/ui/web/static/js/rig-menu.js").read_text(encoding="utf-8")
    assert "{ target_c: v }" in menu and "temperature_c: v" not in menu
