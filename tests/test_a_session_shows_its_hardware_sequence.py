"""A session's hardware sequence, read back onto one clock for the Sessions view.

"these are some plots along the lines of what I was thinking of for the
visualization of image acquisition ... And I think the LED will affect all
embryos, so this shouldn't actually be colored by embryo ... We can also add
the temperature to this plots as additional panel."

What the view draws comes from three records with three ways of keeping time:
a volume's sidecar (UTC with its Z), a brightfield frame's (UTC for the new
stamps, the PC's local time for the old), and temperature.jsonl (UTC with an
offset). A volume or frame from before the hardware was recorded is drawn
from what it kept, and says that it was not recorded.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core.file_store import FileStore
from gently.core.hardware_sequence import session_sequence
from gently.ui.web import auth
from gently.ui.web.routes import sessions as sessions_routes

# Literal epochs and the same moments in UTC, worked out by hand:
# 1794700000 s is 2026-11-14T23:46:40Z.
E0 = 1794700000.0

RECORDED = {
    "laser_config": "488 and 561",
    "lines": [488, 561],
    "powers_pct": {"488": 2.5, "561": 7.5},
    "num_slices": 3,
    "exposure_ms": 20.0,
    "lasers_on_utc": "2026-11-14T23:46:40.100000Z",
    "scan_started_utc": "2026-11-14T23:46:40.350000Z",
    "first_frame_utc": "2026-11-14T23:46:40.400000Z",
    "last_frame_utc": "2026-11-14T23:46:41.200000Z",
    "lasers_off_utc": "2026-11-14T23:46:41.300000Z",
}


def _a_clock_a_test_can_set():
    """Windows has no tzset: a process there cannot change the zone its local
    times are read in, so the tests that need this PC in a known zone skip."""
    if not hasattr(time, "tzset"):
        pytest.skip("this system's local zone cannot be set from a test")


@pytest.fixture
def utc_clock(monkeypatch):
    """The PC's local time is UTC here, so an old local stamp reads plainly."""
    _a_clock_a_test_can_set()
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def _write_volume(store, sid, eid, t, acquired_utc, metadata, side="A", rig_offset_h=0):
    """A volume as the rig writes it: its time in UTC, and in the rig PC's
    local time with no zone, ``rig_offset_h`` hours from UTC."""
    vol = np.zeros((6, 2, 2), np.uint16)
    utc = datetime.fromisoformat(acquired_utc.replace("Z", "+00:00"))
    local = (utc + timedelta(hours=rig_offset_h)).replace(tzinfo=None).isoformat()
    store.put_volume(
        sid,
        eid,
        t,
        vol,
        metadata=metadata,
        side=side,
        acquired_at=local,
        acquired_at_utc=acquired_utc,
    )


@pytest.fixture
def session(tmp_path, utc_clock):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1", nickname="A")
    store.register_embryo("s1", "embryo_2", nickname="B")
    # Recorded: the hardware's own record. The embryo's 561 setting (8.0)
    # was not what the line ran at (7.5, read back), and the record wins.
    _write_volume(
        store,
        "s1",
        "embryo_1",
        1,
        "2026-11-14T23:46:40.350000Z",
        {
            "num_slices": 3,
            "exposure_ms": 20.0,
            "laser_power_488_pct": 2.5,
            "laser_power_561_pct": 8.0,
            "hardware": RECORDED,
        },
    )
    # From before: the embryo's settings and the scan's start, nothing else.
    _write_volume(
        store,
        "s1",
        "embryo_2",
        1,
        "2026-11-14T23:46:45.000000Z",
        {
            "num_slices": 20,
            "exposure_ms": 10.0,
            "laser_power_488_pct": 3.0,
            "laser_power_561_pct": None,
        },
    )
    frame = np.ones((8, 8), np.uint16)
    store.put_snapshot(
        "s1",
        "bf",
        frame,
        metadata={
            "channel": "bf",
            "frame": 1,
            "field": 0,
            "fields": 2,
            "round": 1,
            "exposure_ms": 10.0,
            "light": "led",
            "led_intensity_pct": 30,
            "captured_at": "2026-11-14T23:46:39.050000",
            "light_on_utc": "2026-11-14T23:46:38.000000Z",
            "light_off_utc": "2026-11-14T23:46:39.000000Z",
            "exposed_utc": "2026-11-14T23:46:38.900000Z",
        },
    )
    # A frame from before the light was recorded: when it was filed, in local time.
    store.put_snapshot(
        "s1",
        "bf",
        frame,
        metadata={
            "channel": "bf",
            "frame": 2,
            "field": 1,
            "fields": 2,
            "round": 1,
            "exposure_ms": 10.0,
            "light": "led",
            "led_intensity_pct": 30,
            "captured_at": "2026-11-14T23:46:50",
        },
    )
    # Not a brightfield frame: a snapshot of something else is not on the timeline.
    store.put_snapshot("s1", "lightsheet", frame, metadata={"channel": "488"})
    for i, (water, setpoint) in enumerate([(19.9, 20.0), (20.0, 20.0), (20.1, 20.0)]):
        store.append_temperature_sample(
            "s1",
            {
                "t": f"2026-11-14T23:46:{38 + 5 * i:02d}+00:00",
                "water_c": water,
                "setpoint_c": setpoint,
                "state": "ok",
            },
        )
    return store


def test_a_recorded_volume_is_drawn_from_what_the_hardware_did(session):
    seq = session_sequence(session, "s1")
    v = next(v for v in seq["volumes"] if v["embryo"] == "embryo_1")
    assert v["recorded"] is True
    assert v["lasers_on"] == pytest.approx(E0 + 0.10)
    assert v["scan_started"] == pytest.approx(E0 + 0.35)
    assert v["first_frame"] == pytest.approx(E0 + 0.40)
    assert v["last_frame"] == pytest.approx(E0 + 1.20)
    assert v["lasers_off"] == pytest.approx(E0 + 1.30)
    assert v["lasers"] == {"488": 2.5, "561": 7.5}
    assert v["laser_config"] == "488 and 561"
    assert (v["t"], v["side"], v["slices"], v["exposure_ms"]) == (1, "A", 3, 20.0)


def test_an_unrecorded_volume_says_so_and_spans_only_its_light_time(session):
    seq = session_sequence(session, "s1")
    v = next(v for v in seq["volumes"] if v["embryo"] == "embryo_2")
    assert v["recorded"] is False
    # Which lines it was routed is not known; the embryo's settings are.
    assert v["lasers"] is None
    assert v["settings"] == {"488": 3.0}
    # Its scan began at acquired_at_utc and lasted at least 20 x 10 ms.
    assert v["scan_started"] == pytest.approx(E0 + 5.0)
    assert v["last_frame"] == pytest.approx(E0 + 5.2)
    assert v["lasers_on"] is None and v["lasers_off"] is None


def test_brightfield_frames_belong_to_no_embryo_and_keep_their_light(session):
    seq = session_sequence(session, "s1")
    assert len(seq["bf"]) == 2
    new, old = sorted(seq["bf"], key=lambda f: f["field"])
    assert "embryo" not in new
    assert new["recorded"] is True
    assert (new["light_on"], new["light_off"]) == (
        pytest.approx(E0 - 2.0),
        pytest.approx(E0 - 1.0),
    )
    assert new["exposed"] == pytest.approx(E0 - 1.1)
    assert (new["light"], new["led_pct"], new["exposure_ms"]) == ("led", 30, 10.0)
    # Filed at 23:46:50 local, which is UTC here; nothing more is known.
    assert old["recorded"] is False
    assert old["filed"] == pytest.approx(E0 + 10.0)
    assert old["light_on"] is None and old["exposed"] is None


def test_the_timeline_spans_what_was_acquired_and_names_its_embryos_and_lines(session):
    seq = session_sequence(session, "s1")
    # From the first light on (the brightfield LED) to the last frame filed.
    assert seq["t0"] == pytest.approx(E0 - 2.0)
    assert seq["t1"] == pytest.approx(E0 + 10.0)
    assert seq["embryos"] == [
        {"id": "embryo_1", "label": "A"},
        {"id": "embryo_2", "label": "B"},
    ]
    # Every line the session's volumes show, recorded or set.
    assert seq["lines"] == [488, 561]


def test_temperature_rides_the_same_clock(session):
    seq = session_sequence(session, "s1")
    assert seq["temperature"] == [
        [pytest.approx(E0 - 2.0), 19.9, 20.0],
        [pytest.approx(E0 + 3.0), 20.0, 20.0],
        [pytest.approx(E0 + 8.0), 20.1, 20.0],
    ]


def test_a_long_temperature_log_is_thinned_without_losing_an_excursion(tmp_path):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1")
    _write_volume(store, "s1", "embryo_1", 1, "2026-11-14T23:46:40.000000Z", {"num_slices": 1})
    _write_volume(store, "s1", "embryo_1", 2, "2026-11-15T02:33:20.000000Z", {"num_slices": 1})
    # Ten thousand seconds at 1 Hz, steady but for one second at 25 C.
    path = store._session_dir("s1") / "temperature.jsonl"
    with path.open("w") as fh:
        for i in range(10_000):
            stamp = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(E0 + i)) + "+00:00"
            water = 25.0 if i == 6_123 else 20.0
            fh.write(json.dumps({"t": stamp, "water_c": water, "setpoint_c": 20.0}) + "\n")
    seq = session_sequence(store, "s1")
    temps = seq["temperature"]
    assert 100 < len(temps) <= 4_000
    assert max(row[1] for row in temps) == 25.0
    assert min(row[1] for row in temps) == 20.0
    assert [row[0] for row in temps] == sorted(row[0] for row in temps)


def test_a_two_sided_volume_keeps_each_sides_own_start(tmp_path):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1")
    b_side = {
        **RECORDED,
        "side_began_utc": "2026-11-14T23:46:41.450000Z",
        "first_frame_utc": "2026-11-14T23:46:41.500000Z",
        "last_frame_utc": "2026-11-14T23:46:42.300000Z",
    }
    _write_volume(
        store,
        "s1",
        "embryo_1",
        1,
        "2026-11-14T23:46:41.500000Z",
        {"num_slices": 3, "exposure_ms": 20.0, "hardware": b_side},
        side="B",
    )
    (v,) = session_sequence(store, "s1")["volumes"]
    assert v["side"] == "B"
    assert v["side_began"] == pytest.approx(E0 + 1.45)
    assert v["scan_started"] == pytest.approx(E0 + 0.35)  # the trigger, shared with A


def test_a_reading_that_is_not_a_number_is_left_out_not_a_broken_page(tmp_path, utc_clock):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1")
    _write_volume(
        store,
        "s1",
        "embryo_1",
        1,
        "2026-11-14T23:46:40.350000Z",
        {
            "num_slices": 3,
            "exposure_ms": 20.0,
            "hardware": {**RECORDED, "powers_pct": {"488": float("nan")}},
        },
    )
    path = store._session_dir("s1") / "temperature.jsonl"
    path.write_text(
        '{"t": "2026-11-14T23:46:40+00:00", "water_c": NaN, "setpoint_c": 20.0}\n'
        '{"t": "2026-11-14T23:46:41+00:00", "water_c": 20.0, "setpoint_c": NaN}\n'
    )
    seq = session_sequence(store, "s1")
    assert seq["volumes"][0]["lasers"] == {"488": None}
    assert seq["temperature"] == [[pytest.approx(E0 + 1.0), 20.0, None]]
    json.dumps(seq, allow_nan=False)  # what the page is sent


@pytest.fixture
def pc_an_hour_ahead_of_utc(monkeypatch):
    """This PC's clock is an hour ahead of UTC (POSIX: zone "LOCAL", UTC+1)."""
    _a_clock_a_test_can_set()
    monkeypatch.setenv("TZ", "LOCAL-1")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def test_a_session_from_a_rig_in_another_zone_reads_on_that_rigs_clock(
    tmp_path, pc_an_hour_ahead_of_utc
):
    """Recorded on a rig five hours behind UTC, read on a PC an hour ahead of
    it. A time the rig kept with no zone is the rig's local time, not this
    PC's: read on this PC's clock, the brightfield frame lands six hours from
    its volume."""
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1")
    _write_volume(
        store,
        "s1",
        "embryo_1",
        1,
        "2026-11-14T23:46:40.000000Z",
        {"num_slices": 20, "exposure_ms": 10.0, "laser_power_488_pct": 3.0},
        rig_offset_h=-5,
    )
    store.put_snapshot(
        "s1",
        "bf",
        np.ones((8, 8), np.uint16),
        metadata={
            "channel": "bf",
            "frame": 1,
            "exposure_ms": 10.0,
            "captured_at": "2026-11-14T18:46:50",
        },
    )
    seq = session_sequence(store, "s1")
    assert seq["bf"][0]["filed"] == pytest.approx(E0 + 10.0)
    assert seq["t1"] - seq["t0"] == pytest.approx(10.0)


def test_an_old_volume_with_only_a_local_time_reads_on_its_sessions_clock(
    tmp_path, pc_an_hour_ahead_of_utc
):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.register_embryo("s1", "embryo_1")
    _write_volume(
        store,
        "s1",
        "embryo_1",
        1,
        "2026-11-14T23:46:40.000000Z",
        {"num_slices": 1},
        rig_offset_h=-5,
    )
    # An older volume: its local time only (it predates acquired_at_utc).
    p = store.put_volume(
        "s1", "embryo_1", 2, np.zeros((6, 2, 2), np.uint16), metadata={"num_slices": 1}
    )
    meta = p.with_name(p.stem + ".meta.yaml")
    doc = yaml.safe_load(meta.read_text())
    doc["acquired_at"], doc["acquired_at_utc"] = "2026-11-14T18:56:40", ""
    meta.write_text(yaml.safe_dump(doc))
    old = next(v for v in session_sequence(store, "s1")["volumes"] if v["t"] == 2)
    assert old["scan_started"] == pytest.approx(E0 + 600.0)


def test_with_no_time_kept_both_ways_a_local_time_is_read_on_this_pcs_clock(
    tmp_path, pc_an_hour_ahead_of_utc
):
    """Nothing to learn the rig's clock from: this PC's zone, the last resort, and said."""
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    store.put_snapshot(
        "s1",
        "bf",
        np.ones((8, 8), np.uint16),
        metadata={"channel": "bf", "captured_at": "2026-11-15T00:46:50"},
    )
    seq = session_sequence(store, "s1")
    assert seq["bf"][0]["filed"] == pytest.approx(E0 + 10.0)  # 00:46:50 at UTC+1 is 23:46:50Z


def test_an_empty_session_has_an_empty_timeline(tmp_path):
    store = FileStore(root=tmp_path)
    store.create_session("s1")
    seq = session_sequence(store, "s1")
    assert seq["volumes"] == [] and seq["bf"] == [] and seq["temperature"] == []
    assert seq["t0"] is None and seq["t1"] is None


def _client(store):
    server = MagicMock()
    server.agent_bridge.agent.store = store
    server.agent_bridge.agent.session_id = None
    app = FastAPI()
    app.include_router(sessions_routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_the_sessions_api_serves_a_sessions_hardware_sequence(session):
    r = _client(session).get("/api/sessions/s1/hardware-sequence")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s1"
    assert len(body["volumes"]) == 2 and len(body["bf"]) == 2


def test_an_unknown_session_has_no_hardware_sequence(session):
    r = _client(session).get("/api/sessions/nope/hardware-sequence")
    assert r.status_code == 404
