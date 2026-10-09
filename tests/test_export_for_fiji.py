"""A session exported the way a biologist finds it again.

"a nice export method that can organize and store the data in a neat manner
that is easily usable in fiji … sorted by timepoint or something instead of
uid in filename … easier to find the original imprints of the experiment
etc, or stored with metadata files"
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core.export import export_session, label_for
from gently.core.file_store import FileStore
from gently.ui.web import auth
from gently.ui.web.routes import reveal as reveal_routes
from gently.ui.web.routes import sessions as sessions_routes

pytest.importorskip("tifffile")

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
REVIEW_JS = (WEB / "static" / "js" / "review.js").read_text(encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    return FileStore(root=tmp_path / "data")


def _session(store, sid="s1"):
    store.create_session(sid, name="N2 overnight", description="three embryos until hatching")
    store.register_embryo(
        store_sid := sid,
        "embryo_1",
        nickname="A",
        position_x=-500.0,
        position_y=-400.0,
        role="test",
    )
    store.register_embryo(
        sid, "embryo_2", nickname="ref 2", position_x=-300.0, position_y=-200.0, role="reference"
    )
    store.register_embryo(
        sid, "embryo_3", position_x=0.0, position_y=0.0, role="test"
    )  # no nickname
    for eid, n in (("embryo_1", 3), ("embryo_2", 2)):
        for tp in range(1, n + 1):
            vol = np.full((4, 8, 8), tp, dtype=np.uint16)
            store.put_volume(
                sid,
                eid,
                tp,
                vol,
                metadata={"num_slices": 4, "exposure_ms": 10.0, "laser_power_488_pct": 3.0},
            )
            store.store_prediction(
                1, sid, eid, tp, ["bean", "comma", "1_5_fold"][tp - 1], confidence=0.8
            )
    # DIC frames filed by uuid, out of frame order on disk
    for frame, when in ((2, "2026-10-04T22:00:00"), (1, "2026-10-04T21:30:00")):
        store.put_snapshot(
            sid,
            "dic",
            np.zeros((6, 9), dtype=np.uint16),
            metadata={
                "channel": "dic",
                "frame": frame,
                "captured_at": when,
                "position": {"x": -440.0, "y": -320.0},
            },
        )
    store.save_acquisition_plan(
        sid,
        {
            "interval_seconds": 600,
            "num_slices": 4,
            "stop_condition": {"kind": "hatching"},
            "dic": {"enabled": True, "every_seconds": 1800, "light": "led"},
        },
    )
    sd = store._session_dir(sid)
    (sd / "timelapse.yaml").write_text(
        yaml.safe_dump(
            {
                "status": "completed",
                "started_at": "2026-10-04T21:00:00",
                "embryos": {"embryo_1": {"is_complete": True, "total_exposure_ms": 300.0}},
            }
        ),
        encoding="utf-8",
    )
    (sd / "events.jsonl").write_text(
        "\n".join(
            json.dumps(r)
            for r in (
                {
                    "event_type": "ACQUISITION_STARTED",
                    "data": {"embryo_ids": ["embryo_1"]},
                    "timestamp": "2026-10-04T21:00:00",
                },
                {
                    "event_type": "STATUS_CHANGED",
                    "data": {"service": "mesh"},
                    "timestamp": "2026-10-04T21:00:01",
                },
                {
                    "event_type": "HATCHING_DETECTED",
                    "data": {"embryo_id": "embryo_1"},
                    "timestamp": "2026-10-05T00:50:00",
                },
            )
        ),
        encoding="utf-8",
    )
    store.append_temperature_sample(
        sid, {"t": "2026-10-04T21:00:00", "water_c": 20.1, "setpoint_c": 20.0, "state": "locked"}
    )
    return store_sid


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TestTheLayout:
    def test_one_folder_per_embryo_named_by_what_it_was_called(self, store, tmp_path):
        sid = _session(store)
        out = export_session(store, sid)
        assert out == Path(store.root) / "exports" / store._session_dir(sid).name
        assert sorted(p.name for p in out.iterdir() if p.is_dir()) == [
            "A_embryo_1",
            "dic",
            "embryo_3",
            "metadata",
            "ref-2_embryo_2",
        ]

    def test_volumes_and_frames_sort_in_time_order(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        vols = sorted(p.name for p in (out / "A_embryo_1" / "volumes").iterdir())
        assert vols == ["A_embryo_1_t0001.tif", "A_embryo_1_t0002.tif", "A_embryo_1_t0003.tif"]
        dic = sorted(p.name for p in (out / "dic").iterdir() if p.suffix == ".tif")
        assert dic == ["dic_f0001_20261004-213000.tif", "dic_f0002_20261004-220000.tif"]
        import tifffile

        assert tifffile.imread(out / "A_embryo_1" / "volumes" / "A_embryo_1_t0002.tif").max() == 2

    def test_copies_not_links(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        exported = out / "A_embryo_1" / "volumes" / "A_embryo_1_t0001.tif"
        original = Path(store.get_volume_path(sid, "embryo_1", 1))
        assert (
            exported.stat().st_ino != original.stat().st_ino
            or exported.stat().st_dev != original.stat().st_dev
        )


class TestTheRecord:
    def test_the_metadata_travels_as_kept_and_as_read(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        for name in (
            "session.yaml",
            "acquisition.yaml",
            "timelapse.yaml",
            "events.jsonl",
            "temperature.jsonl",
        ):
            assert (out / "metadata" / name).is_file(), name
        embryos = {r["embryo_id"]: r for r in _rows(out / "embryos.csv")}
        assert embryos["embryo_1"]["label"] == "A_embryo_1"
        assert (
            embryos["embryo_1"]["timepoints"] == "3"
            and embryos["embryo_1"]["last_stage"] == "1_5_fold"
        )
        assert (
            embryos["embryo_1"]["complete"] == "True"
            and embryos["embryo_1"]["total_exposure_ms"] == "300.0"
        )
        assert (
            embryos["embryo_2"]["role"] == "reference" and embryos["embryo_2"]["x_um"] == "-300.0"
        )
        calls = _rows(out / "stage_calls.csv")
        assert [(c["label"], c["timepoint"], c["stage"]) for c in calls][:3] == [
            ("A_embryo_1", "1", "bean"),
            ("A_embryo_1", "2", "comma"),
            ("A_embryo_1", "3", "1_5_fold"),
        ]
        events = _rows(out / "events.csv")
        assert [e["type"] for e in events] == [
            "ACQUISITION_STARTED",
            "HATCHING_DETECTED",
        ]  # no status chatter
        assert _rows(out / "temperature.csv")[0]["water_c"] == "20.1"
        vols = _rows(out / "A_embryo_1" / "volumes.csv")
        assert vols[0]["file"] == "volumes/A_embryo_1_t0001.tif" and vols[0]["z"] == "4"
        assert vols[0]["laser_488_pct"] == "3.0" and vols[0]["exposure_ms"] == "10.0"
        dic = _rows(out / "dic" / "dic.csv")
        assert [d["frame"] for d in dic] == ["1", "2"] and dic[0]["x_um"] == "-440.0"

    def test_the_readme_points_back_at_the_originals(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        text = (out / "README.txt").read_text(encoding="utf-8")
        assert text.startswith("N2 overnight\n")
        assert f"Originals: {store._session_dir(sid)}" in text
        assert "three embryos until hatching" in text
        assert "Interval: every 600 s" in text and "DIC overview: every 1800 s, led" in text
        assert "A_embryo_1/   role test, 3 timepoints, last stage 1_5_fold, complete" in text
        assert "Import > Image Sequence" in text
        assert "copies, not links" in text

    def test_the_plan_as_the_run_wrote_it(self, store):
        # The orchestrator records the stop condition as a string beside a
        # condition_value, not as a dict. An overnight run exported this way
        # used to fail with "'str' object has no attribute 'get'".
        sid = _session(store)
        store.save_acquisition_plan(
            sid,
            {
                "interval_seconds": 600,
                "stop_condition": "duration:12h",
                "condition_value": None,
                "num_slices": None,
                "dic": {"enabled": True, "every_seconds": 1800, "light": "led"},
            },
        )
        text = (export_session(store, sid) / "README.txt").read_text(encoding="utf-8")
        assert "Stop: duration:12h" in text
        store.save_acquisition_plan(sid, {"stop_condition": "timepoints", "condition_value": 40})
        text = (export_session(store, sid) / "README.txt").read_text(encoding="utf-8")
        assert "Stop: timepoints 40" in text

    def test_a_destination_of_choice(self, store, tmp_path):
        sid = _session(store)
        out = export_session(store, sid, tmp_path / "usb")
        assert out.parent == tmp_path / "usb" and (out / "README.txt").is_file()

    def test_progress_counts_every_file(self, store):
        sid = _session(store)
        seen = []
        export_session(store, sid, progress=lambda d, t, w: seen.append((d, t)))
        done, total = seen[-1]
        assert done == total and total == 5 + 2 + 2 + 5 + 6
        # 5 volumes, 2 DIC frames copied and 2 into the movie, 5 projections
        # (filed with the volumes), six records


class TestLabels:
    def test_labels_are_safe_and_distinct(self):
        assert label_for({"embryo_id": "embryo_1", "nickname": "A"}) == "A_embryo_1"
        assert (
            label_for({"embryo_id": "embryo_2", "nickname": "the fast one!"})
            == "the-fast-one_embryo_2"
        )
        assert label_for({"embryo_id": "embryo_3", "nickname": None}) == "embryo_3"
        assert label_for({"embryo_id": "embryo_4", "nickname": "embryo_4"}) == "embryo_4"


# ── the routes ──────────────────────────────────────────────────────────────


def _client(store, control=True):
    server = MagicMock()
    server.agent_bridge.agent.store = store
    server.agent_bridge.agent.session_id = None
    app = FastAPI()
    app.include_router(sessions_routes.create_router(server))
    app.include_router(reveal_routes.create_router(server))
    if control:
        app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


class TestTheRoute:
    def test_export_runs_in_the_background_and_reports_where_it_went(self, store):
        sid = _session(store)
        c = _client(store)
        idle = c.get(f"/api/sessions/{sid}/export").json()
        assert idle["state"] == "idle" and idle["default_dest"] == str(Path(store.root) / "exports")
        started = c.post(f"/api/sessions/{sid}/export", json={})
        assert started.status_code == 200 and started.json()["state"] in ("running", "done")
        for _ in range(100):
            job = c.get(f"/api/sessions/{sid}/export").json()
            if job["state"] != "running":
                break
            time.sleep(0.05)
        assert job["state"] == "done", job
        assert job["done"] == job["total"] and Path(job["path"]).joinpath("README.txt").is_file()
        # and the export folder is a thing the file manager can be pointed at
        r = c.post("/api/reveal", json={"what": "export", "session_id": sid, "action": "path"})
        assert r.status_code == 200, r.text
        assert Path(r.json()["path"]) == Path(job["path"])

    def test_a_relative_destination_is_refused(self, store):
        sid = _session(store)
        r = _client(store).post(f"/api/sessions/{sid}/export", json={"dest": "exports-here"})
        assert r.status_code == 400

    def test_an_unknown_session_is_404(self, store):
        assert _client(store).post("/api/sessions/nope/export", json={}).status_code == 404


class TestThePane:
    def test_the_header_offers_the_export_and_says_what_it_is(self):
        for needle in (
            "Export for Fiji",
            "startExport(",
            "pollExport(",
            "/export",
            "what: 'export'",
        ):
            assert needle in REVIEW_JS, needle
        assert "Copies, not links" in REVIEW_JS


class TestDicMovie:
    """ "can you make an avi for the dic dataset?" — dic/dic.avi, every frame
    in time order, Motion JPEG so Fiji opens it."""

    def _frames(self, path):
        import cv2

        cap = cv2.VideoCapture(str(path))
        assert cap.isOpened(), path
        n = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            n += 1
            shape = frame.shape
        cap.release()
        return n, shape

    def test_the_export_has_the_dic_frames_as_a_movie(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        n, shape = self._frames(out / "dic" / "dic.avi")
        # Motion JPEG rounds an odd width down (9 -> 8); the camera's are even.
        assert n == 2 and shape[0] == 6 and shape[1] in (8, 9)
        text = (out / "README.txt").read_text(encoding="utf-8")
        assert "dic/dic.avi" in text and "Motion JPEG" in text

    def test_no_dic_frames_no_movie(self, store):
        sid = "bare"
        store.create_session(sid, name="bare")
        store.register_embryo(sid, "embryo_1", position_x=0.0, position_y=0.0, role="test")
        out = export_session(store, sid)
        assert not (out / "dic" / "dic.avi").exists()

    def test_a_folder_of_frames_is_enough(self, tmp_path):
        """An export made before there was a movie, or any folder of
        dic_f*.tif frames, can have one made after the fact."""
        import tifffile

        from gently.core.export import dic_movie

        d = tmp_path / "dic"
        d.mkdir()
        rng = np.random.default_rng(0)
        for i in (3, 1, 2):
            tifffile.imwrite(
                d / f"dic_f{i:04d}_20261006-10{i:02d}00.tif",
                rng.integers(60, 1000, (16, 20), dtype=np.uint16),
            )
        seen = []
        out = dic_movie(d, progress=lambda i, n, what: seen.append((i, n, what)))
        assert out == d / "dic.avi"
        assert self._frames(out) == (3, (16, 20, 3))
        assert [s[:2] for s in seen] == [(1, 3), (2, 3), (3, 3)]
        assert seen[0][2].endswith("dic_f0001_20261006-100100.tif")

    def test_the_progress_counts_the_movie(self, store):
        sid = _session(store)
        seen = []
        export_session(store, sid, progress=lambda d, t, w: seen.append((d, t, w)))
        totals = {t for _, t, _ in seen}
        assert len(totals) == 1
        assert seen[-1][0] == seen[-1][1]
        assert any(w.startswith("dic.avi") for _, _, w in seen)


class TestMovieFitsAPlainAvi:
    """ "frames that are in the raw data are missing in the video": past 1 GB
    an AVI continues in OpenDML chunks that many players do not read, and a
    1.5 GB movie showed 922 of its 1336 frames in them. A movie is now made
    to fit in one chunk, at a smaller size when it must."""

    def test_the_scale_fits_the_frames_in_the_limit(self):
        """Measured with the writer itself: the bytes it spends on the sample
        frames say what the whole run would cost."""
        import os
        import tempfile

        import cv2

        from gently.core.export import _fit_scale

        rng = np.random.default_rng(1)
        frames = [rng.integers(0, 255, (256, 256), dtype=np.uint8) for _ in range(4)]  # noisy
        fd, tmp = tempfile.mkstemp(suffix=".avi")
        os.close(fd)
        wr = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*"MJPG"), 10, (256, 256), isColor=True)
        for f in frames:
            wr.write(cv2.cvtColor(f, cv2.COLOR_GRAY2BGR))
        wr.release()
        per = os.path.getsize(tmp) / 4
        os.remove(tmp)
        assert _fit_scale(frames, 3, limit=int(per * 10)) == 1.0, "three fit in ten"
        s = _fit_scale(frames, 40, limit=int(per * 10))
        assert 0.1 <= s < 1.0
        # Shrunk by s on each side, 40 of them fit (bytes go with area).
        assert (s * s) * per * 40 * 1.1 <= per * 10 * 1.05
        assert _fit_scale(frames, 10**9, limit=1) == 0.1, "never below a tenth"
        assert _fit_scale([], 100, limit=1) == 1.0, "nothing to measure, nothing to shrink"

    def test_a_long_run_is_written_smaller_not_cut(self, tmp_path, monkeypatch):
        import cv2
        import tifffile

        from gently.core import export as export_mod
        from gently.core.export import dic_movie

        d = tmp_path / "dic"
        d.mkdir()
        rng = np.random.default_rng(0)
        for i in range(1, 7):
            tifffile.imwrite(
                d / f"dic_f{i:04d}_20261006-10{i:02d}00.tif",
                rng.integers(60, 1000, (200, 240), dtype=np.uint16),
            )
        # A limit so small that six frames must shrink to fit it.
        monkeypatch.setattr(export_mod, "AVI_CLASSIC_BYTES", 40_000)
        out = dic_movie(d, label=False)
        cap = cv2.VideoCapture(str(out))
        n, w, h = 0, int(cap.get(3)), int(cap.get(4))
        while cap.read()[0]:
            n += 1
        cap.release()
        assert n == 6, "every frame is there"
        assert w < 240 and h < 200, "at a smaller size"
        assert (d / "dic.avi").stat().st_size < 60_000
        # With room to spare, full size as before.
        monkeypatch.setattr(export_mod, "AVI_CLASSIC_BYTES", 1_000_000_000)
        out = dic_movie(d, label=False)
        cap = cv2.VideoCapture(str(out))
        assert (int(cap.get(3)), int(cap.get(4))) == (240, 200)
        cap.release()


class TestCorrectedDicMovie:
    """ "can you also output the flat fielded movie? using the flat field
    image?" — dic_corrected.avi: each frame with the dark and flat dic.csv
    names for it divided out, beside dic.avi."""

    @staticmethod
    def _dic_folder(tmp_path):
        """Three frames lit through a strong left-to-right gradient, with the
        dark and flat that explain it, and a dic.csv that names them."""
        import tifffile

        d = tmp_path / "dic"
        (d / "references" / "r1").mkdir(parents=True)
        h, w = 16, 32
        dark = np.full((h, w), 100, dtype=np.uint16)
        gain = np.tile(np.linspace(100, 900, w), (h, 1))
        flat = (dark + gain).astype(np.uint16)
        tifffile.imwrite(d / "references" / "r1" / "dark.tif", dark)
        tifffile.imwrite(d / "references" / "r1" / "flat.tif", flat)
        rows = []
        for i in range(1, 4):
            # A specimen at transmission 0.5 with a darker body in the middle:
            # under the gradient it looks lit from the right; corrected, it is level.
            t = np.full((h, w), 0.5)
            t[5:11, 12:20] = 0.2
            frame = (dark + t * gain).astype(np.uint16)
            name = f"dic_f{i:04d}_20261006-10{i:02d}00.tif"
            tifffile.imwrite(d / name, frame)
            rows.append(
                {
                    "file": f"dic/{name}",
                    "frame": i,
                    "captured_at": f"2026-10-06T10:{i:02d}:00",
                    "dark": "references/r1/dark.tif",
                    "flat": "references/r1/flat.tif",
                }
            )
        with open(d / "dic.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        return d

    @staticmethod
    def _first_frame(path):
        import cv2

        cap = cv2.VideoCapture(str(path))
        ok, frame = cap.read()
        cap.release()
        assert ok
        return frame[:, :, 0].astype(float)

    def test_the_gradient_is_divided_out(self, tmp_path):
        from gently.core.export import dic_movie

        d = self._dic_folder(tmp_path)
        raw = dic_movie(d, label=False)
        fixed = dic_movie(d, label=False, corrected=True)
        assert raw == d / "dic.avi" and fixed == d / "dic_corrected.avi"
        r, c = self._first_frame(raw), self._first_frame(fixed)
        # Raw: the left edge is dark and the right bright. Corrected: level.
        assert r[:, :4].mean() + 100 < r[:, -4:].mean()
        assert abs(c[:, :4].mean() - c[:, -4:].mean()) < 12

    def test_without_references_there_is_nothing_to_correct(self, tmp_path):
        import tifffile

        from gently.core.export import dic_movie

        d = tmp_path / "dic"
        d.mkdir()
        tifffile.imwrite(d / "dic_f0001.tif", np.full((8, 8), 300, dtype=np.uint16))
        assert dic_movie(d, corrected=True) is None
        assert not (d / "dic_corrected.avi").exists()

    def test_the_export_writes_both_when_the_session_had_references(self, store):
        import tifffile

        sid = _session(store)
        sd = store._session_dir(sid)
        ref = sd / "calibration" / "brightfield" / "20261004_210000"
        ref.mkdir(parents=True)
        tifffile.imwrite(ref / "dark.tif", np.full((6, 9), 10, dtype=np.uint16))
        tifffile.imwrite(ref / "flat.tif", np.full((6, 9), 500, dtype=np.uint16))
        (ref / "brightfield.yaml").write_text(
            yaml.safe_dump(
                {
                    "record": "20261004_210000",
                    # The fixture's frames name no light, so they are room-lit
                    # frames, and this is the record for room light.
                    "spec": {"light": "room"},
                    "dark": {"file": "dark.tif"},
                    "flat": {"file": "flat.tif"},
                }
            ),
            encoding="utf-8",
        )
        seen = []
        out = export_session(store, sid, progress=lambda d, t, w: seen.append((d, t, w)))
        assert (out / "dic" / "dic.avi").exists()
        assert (out / "dic" / "dic_corrected.avi").exists()
        assert seen[-1][0] == seen[-1][1]
        assert any(w.startswith("dic_corrected.avi") for _, _, w in seen)
        assert "dic_corrected.avi" in (out / "README.txt").read_text(encoding="utf-8")


class TestSpimMovie:
    """ "spim movie making [is] separate stuff … they need separate
    behaviours": a volume is a stack, so there are two ways to watch it."""

    @staticmethod
    def _count(path):
        import cv2

        cap = cv2.VideoCapture(str(path))
        n = 0
        while cap.read()[0]:
            n += 1
        cap.release()
        return n

    def test_projections_one_frame_per_timepoint(self, store):
        from gently.core.export import spim_movie

        sid = _session(store)
        out = export_session(store, sid)
        vols = out / "A_embryo_1" / "volumes"
        movie = spim_movie(vols, view="projection")
        assert movie == vols / "spim_projection.avi"
        assert self._count(movie) == 3

    def test_slices_every_slice_stack_by_stack(self, store):
        from gently.core.export import spim_movie

        sid = _session(store)
        out = export_session(store, sid)
        vols = out / "A_embryo_1" / "volumes"
        movie = spim_movie(vols, view="slices")
        assert movie == vols / "spim_slices.avi"
        assert self._count(movie) == 3 * 4  # three timepoints of four slices

    def test_the_sessions_own_volumes_folder_works_too(self, store):
        from gently.core.export import spim_movie

        sid = _session(store)
        vols = store._session_dir(sid) / "embryos" / "embryo_2" / "volumes"
        assert self._count(spim_movie(vols)) == 2

    def test_no_volumes_no_movie_and_no_other_view(self, tmp_path):
        from gently.core.export import spim_movie

        assert spim_movie(tmp_path) is None
        with pytest.raises(ValueError):
            spim_movie(tmp_path, view="sideways")


class TestMovieButton:
    """ "need a make movie button that is standalone too": any folder, from
    the page, one movie at a time."""

    @pytest.fixture(autouse=True)
    def fresh(self, monkeypatch):
        monkeypatch.setattr(sessions_routes, "_MOVIES", {"state": "idle"})
        monkeypatch.setattr(reveal_routes.os_reveal, "is_local", lambda host: True)

    def _wait(self, c):
        for _ in range(200):
            job = c.get("/api/movies").json()
            if job["state"] != "running":
                return job
            time.sleep(0.05)
        return job

    def test_a_dic_movie_of_an_export_on_disk(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        c = _client(store)
        assert c.get("/api/movies").json()["state"] == "idle"
        r = c.post("/api/movies", json={"kind": "dic", "folder": str(out)})
        assert r.status_code == 200, r.text
        job = self._wait(c)
        assert job["state"] == "done", job
        # The export's root was given; its dic/ folder is where the frames are.
        assert Path(job["folder"]) == out / "dic"
        assert job["outputs"] == ["dic.avi"]  # no references in this session…
        assert "no dark and flat" in job["note"]  # …and it says so
        assert job["done"] == job["total"]
        # and the folder is a thing the file manager can be pointed at
        r = c.post("/api/reveal", json={"what": "movie", "action": "path"})
        assert r.status_code == 200 and Path(r.json()["path"]) == out / "dic"

    def test_a_spim_movie_of_a_volumes_folder(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        c = _client(store)
        r = c.post(
            "/api/movies",
            json={"kind": "spim", "folder": str(out / "A_embryo_1"), "view": "slices"},
        )
        assert r.status_code == 200, r.text
        job = self._wait(c)
        assert job["state"] == "done" and job["outputs"] == ["spim_slices.avi"]
        assert (out / "A_embryo_1" / "volumes" / "spim_slices.avi").is_file()

    @pytest.mark.parametrize(
        "body, status",
        [
            ({"kind": "gif", "folder": "C:/x"}, 400),
            ({"kind": "dic"}, 400),
            ({"kind": "dic", "folder": "relative/here"}, 400),
            ({"kind": "spim", "folder": "<missing>"}, 404),
        ],
    )
    def test_what_cannot_be_a_movie(self, store, tmp_path, body, status):
        # An absolute path on every platform, to a folder that is not there.
        if body.get("folder") == "<missing>":
            body = dict(body, folder=str(tmp_path / "surely" / "not" / "here"))
        assert _client(store).post("/api/movies", json=body).status_code == status

    def test_a_folder_without_the_right_files(self, store, tmp_path):
        c = _client(store)
        r = c.post("/api/movies", json={"kind": "dic", "folder": str(tmp_path)})
        assert r.status_code == 400 and "DIC frames" in r.json()["detail"]
        r = c.post("/api/movies", json={"kind": "spim", "folder": str(tmp_path)})
        assert r.status_code == 400 and "volumes" in r.json()["detail"]

    def test_one_at_a_time(self, store):
        sessions_routes._MOVIES.update({"state": "running"})
        r = _client(store).post("/api/movies", json={"kind": "dic", "folder": "C:/"})
        assert r.status_code == 409

    def test_without_control_no_movie(self, store):
        r = _client(store, control=False).post("/api/movies", json={"kind": "dic", "folder": "C:/"})
        assert r.status_code == 403

    def test_no_movie_yet_is_nothing_to_show(self, store):
        r = _client(store).post("/api/reveal", json={"what": "movie", "action": "path"})
        assert r.status_code == 404

    def test_the_page_has_the_two_buttons_with_their_own_forms(self):
        for needle in (
            "askMovie('dic')",
            "askMovie('spim')",
            "session-movie-corrected",
            'name="session-movie-view"',
            'value="slices"',
            "startMovie(",
            "pollMovie(",
            "/api/movies",
            "what: 'movie'",
            "browseMovieFolder(",
        ):
            assert needle in REVIEW_JS, needle


class TestEmbryoCrops:
    """ "i need to crop the 4 embryos into bboxes and have them separate":
    one box per embryo, the same in every frame, each a folder of its own."""

    @staticmethod
    def _field(tmp_path, n_frames=3, embryos=((20, 50, 30, 50), (70, 100, 110, 135))):
        """Frames of a bright field with two dark embryos (rows and columns
        given as y0, y1, x0, x1), the dark and flat that explain the field,
        and the dic.csv that names them."""
        import tifffile

        d = tmp_path / "dic"
        (d / "references" / "r1").mkdir(parents=True)
        h, w = 120, 160
        dark = np.full((h, w), 100, dtype=np.uint16)
        gain = np.tile(np.linspace(300, 700, w), (h, 1))
        flat = (dark + gain).astype(np.uint16)
        tifffile.imwrite(d / "references" / "r1" / "dark.tif", dark)
        tifffile.imwrite(d / "references" / "r1" / "flat.tif", flat)
        rows = []
        for i in range(1, n_frames + 1):
            t = np.full((h, w), 0.6)
            for y0, y1, x0, x1 in embryos:
                t[y0:y1, x0:x1] = 0.15  # by default A: 30 tall x 20 wide, B: 30 x 25
            frame = (dark + t * gain).astype(np.uint16)
            name = f"dic_f{i:04d}_20261006-10{i:02d}00.tif"
            tifffile.imwrite(d / name, frame)
            rows.append(
                {
                    "file": f"dic/{name}",
                    "frame": i,
                    "captured_at": f"2026-10-06T10:{i:02d}:00",
                    "dark": "references/r1/dark.tif",
                    "flat": "references/r1/flat.tif",
                }
            )
        with open(d / "dic.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        return d

    def test_the_boxes_are_found_near_the_seeds_and_sized_alike(self, tmp_path):
        from gently.core.export import find_embryo_boxes

        d = self._field(tmp_path)
        boxes = find_embryo_boxes(d, {"a": (40, 35), "b": (122, 85)}, margin=5)
        a, b = boxes["a"], boxes["b"]
        # Each holds its embryo with the margin, and both are the same size.
        assert a[0] <= 30 and a[1] <= 20 and a[2] >= 50 and a[3] >= 50
        assert b[0] <= 110 and b[1] <= 70 and b[2] >= 135 and b[3] >= 100
        assert (a[2] - a[0], a[3] - a[1]) == (b[2] - b[0], b[3] - b[1])
        # The blur widens a blob by a pixel or two a side.
        assert 25 + 10 <= b[2] - b[0] <= 25 + 14 and 30 + 10 <= b[3] - b[1] <= 30 + 14

    def test_seeds_are_turned_to_the_frames_way_up(self, tmp_path):
        """The marking's preview and the filed frame need not share a way
        up: on this rig the frame is the preview turned by 180°. The seeds
        are scored each way round against the dark blobs, and the way that
        lands on them wins."""
        from gently.core.export import orient_seeds

        # Two embryos laid out with no symmetry, at (30, 30) and (100, 40)
        # in a 160 x 120 field, so only one way up lands on both.
        d = self._field(tmp_path, embryos=((15, 45, 20, 40), (30, 50, 90, 110)))
        upright = {"a": (30.0, 30.0), "b": (100.0, 40.0)}
        assert orient_seeds(d, upright) == upright
        # The same two, as a preview turned by 180° would place them.
        turned = {"a": (160 - 30.0, 120 - 30.0), "b": (160 - 100.0, 120 - 40.0)}
        assert orient_seeds(d, turned) == upright
        # Mirrored in one axis only, likewise.
        assert orient_seeds(d, {"a": (160 - 30.0, 30.0), "b": (160 - 100.0, 40.0)}) == upright
        assert orient_seeds(d, {"a": (30.0, 120 - 30.0), "b": (100.0, 120 - 40.0)}) == upright
        assert orient_seeds(d, {}) == {}

    def test_claude_finds_the_boxes_and_the_blobs_stand_in_where_it_did_not(
        self, tmp_path, monkeypatch
    ):
        """ "replace the box finder with claude based setup": the vision model's
        boxes come first; an embryo it did not see keeps the blob's box; and
        with nothing from it at all, the blobs are the answer as before."""
        from gently.core.export import find_embryo_boxes

        d = self._field(tmp_path)  # embryos at (40, 35) and (122, 85)
        seeds = {"a": (40.0, 35.0), "b": (122.0, 85.0)}
        asked = []

        def fake_claude(img, dark=None, flat=None, **kw):
            asked.append(img.shape)
            return [(28, 18, 52, 52)]  # a, a little looser than the blob; b unseen

        import gently.core.embryo_finding as finding

        monkeypatch.setattr(finding, "claude_boxes", fake_claude)
        boxes = find_embryo_boxes(d, seeds, margin=5, method="claude")
        assert asked, "Claude was asked"
        a, b = boxes["a"], boxes["b"]
        assert a[0] <= 28 and a[1] <= 18 and a[2] >= 52 and a[3] >= 52, "Claude's box for a"
        assert b[0] <= 110 and b[1] <= 70 and b[2] >= 135 and b[3] >= 100, "the blob's box for b"
        assert (a[2] - a[0], a[3] - a[1]) == (b[2] - b[0], b[3] - b[1]), "sized alike"

        monkeypatch.setattr(finding, "claude_boxes", lambda *a, **k: [])
        assert find_embryo_boxes(d, seeds, margin=5, method="claude") == find_embryo_boxes(
            d, seeds, margin=5, method="blobs"
        )

    def test_auto_is_claude_with_a_key_and_the_blobs_without(self, tmp_path, monkeypatch):
        import gently.core.embryo_finding as finding
        from gently.core.export import find_embryo_boxes

        d = self._field(tmp_path)
        seeds = {"a": (40.0, 35.0)}
        asked = []
        monkeypatch.setattr(finding, "claude_boxes", lambda *a, **k: (asked.append(1), [])[1])
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        find_embryo_boxes(d, seeds, method="auto")
        assert asked
        asked.clear()
        monkeypatch.delenv("ANTHROPIC_API_KEY")
        find_embryo_boxes(d, seeds, method="auto")
        assert not asked
        with pytest.raises(ValueError):
            find_embryo_boxes(d, seeds, method="guess")

    def test_a_seed_with_nothing_near_it_still_gets_a_box(self, tmp_path):
        from gently.core.export import find_embryo_boxes

        d = self._field(tmp_path)
        boxes = find_embryo_boxes(d, {"a": (40, 35), "ghost": (80, 60)}, margin=5)
        g = boxes["ghost"]
        assert 20 + 10 <= g[2] - g[0] <= 20 + 14 and 30 + 10 <= g[3] - g[1] <= 30 + 14
        assert g[0] < 80 < g[2] and g[1] < 60 < g[3]

    def test_each_embryo_gets_its_own_folder_of_crops_and_movies(self, tmp_path):
        import cv2
        import tifffile

        from gently.core.export import dic_crops

        d = self._field(tmp_path)
        boxes = {"a": (25, 15, 55, 55), "b": (105, 65, 140, 105)}
        seen = []
        root = dic_crops(
            d,
            boxes,
            progress=lambda i, n, w: seen.append((i, n)),
            notes={"b": "dead; kept as an anomalous case"},
        )
        assert root == d / "embryos"
        assert (root / "boxes.png").is_file() and (root / "boxes.csv").is_file()
        for name, box in boxes.items():
            e = root / name
            crops = sorted(p.name for p in (e / "raw").glob(f"{name}_f*.tif"))
            assert crops == [f"{name}_f000{i}_20261006-100{i}00.tif" for i in (1, 2, 3)]
            assert sorted(p.name for p in (e / "corrected").glob("*.tif")) == crops
            crop = tifffile.imread(e / "raw" / crops[0])
            assert crop.shape == (box[3] - box[1], box[2] - box[0]) and crop.dtype == np.uint16
            fixed = tifffile.imread(e / "corrected" / crops[0])
            assert fixed.shape == crop.shape and fixed.dtype == np.uint16
            # Shading corrected, dark included: background is level and at
            # the mean of (flat - dark) times the specimen's transmission.
            bg = np.r_[fixed[:, :3].ravel(), fixed[:, -3:].ravel()].astype(float)
            assert abs(bg.mean() - 0.6 * 500) < 15 and bg.std() < 15
            assert tifffile.imread(e / "dark.tif").shape == crop.shape
            assert tifffile.imread(e / "flat.tif").shape == crop.shape
            rows = list(csv.DictReader(open(e / "metadata.csv", encoding="utf-8")))
            assert [r["frame"] for r in rows] == ["1", "2", "3"]
            assert rows[0]["source_frame"] == "dic_f0001_20261006-100100.tif"
            assert rows[0]["file_name"] == f"raw/{crops[0]}"
            assert rows[0]["corrected_file"] == f"corrected/{crops[0]}"
            assert rows[0]["dark_file"] == "dark.tif" and rows[0]["flat_file"] == "flat.tif"
            assert [r["elapsed_s"] for r in rows] == ["0.0", "60.0", "120.0"]
            assert rows[0]["embryo"] == name
            for movie in (e / f"{name}.avi", e / f"{name}_corrected.avi"):
                cap = cv2.VideoCapture(str(movie))
                assert cap.isOpened(), movie
                n = 0
                while cap.read()[0]:
                    n += 1
                cap.release()
                assert n == 3, movie
        assert seen[-1] == (3, 3)
        card = (root / "README.md").read_text(encoding="utf-8")
        assert card.startswith("---\npretty_name:") and "imagefolder" in card
        assert "(raw - dark) / (flat - dark)" in card and "huggingface-cli upload" in card
        # What was said about an embryo travels with it: card, boxes, every row.
        assert "| b | 105, 65, 140, 105 | dead; kept as an anomalous case |" in card
        boxes_rows = {r["embryo"]: r for r in csv.DictReader(open(root / "boxes.csv"))}
        assert boxes_rows["b"]["note"] == "dead; kept as an anomalous case"
        assert boxes_rows["a"]["note"] == ""
        b_rows = list(csv.DictReader(open(root / "b" / "metadata.csv", encoding="utf-8")))
        assert {r["note"] for r in b_rows} == {"dead; kept as an anomalous case"}

    def test_the_corrected_crop_is_level_where_the_raw_one_slopes(self, tmp_path):
        import cv2

        from gently.core.export import dic_crops

        d = self._field(tmp_path)
        root = dic_crops(d, {"b": (105, 65, 140, 105)}, label=False)

        def first(path):
            cap = cv2.VideoCapture(str(path))
            ok, f = cap.read()
            cap.release()
            assert ok
            return f[:, :, 0].astype(float)

        raw, fixed = first(root / "b" / "b.avi"), first(root / "b" / "b_corrected.avi")
        # Background columns left and right of the embryo in the crop.
        assert raw[:, :3].mean() + 20 < raw[:, -3:].mean()
        assert abs(fixed[:, :3].mean() - fixed[:, -3:].mean()) < 12


class TestCropsInTheExport:
    """ "can these be part of the gently export features?" — where the
    session has an Operate marking, the export cuts the embryos out too,
    and a button does it for an export that already exists."""

    @staticmethod
    def _mark(store, sid):
        """The Operate tab's marking: a 1/3-scale preview of the field with
        each embryo's pixel position and stage position. The fixture's DIC
        frames are 6 x 9; the preview is 2 x 3."""
        from gently.core.export import marking_seeds

        store.put_snapshot(
            sid,
            "operate_marked",
            np.zeros((2, 3), dtype=np.uint16),
            metadata={
                "kind": "operate_marking",
                "frame": {"width": 3.0, "height": 2.0, "downsample": 3.0},
                "embryos": [
                    {"pixel_x": 1.0, "pixel_y": 0.5, "stage_x_um": -500.0, "stage_y_um": -400.0},
                    {"pixel_x": 2.5, "pixel_y": 1.5, "stage_x_um": -300.0, "stage_y_um": -200.0},
                    {"pixel_x": 0.5, "pixel_y": 1.5, "stage_x_um": 9000.0, "stage_y_um": 9000.0},
                ],
            },
        )
        return marking_seeds

    def test_the_marking_says_where_each_embryo_is_by_its_label(self, store):
        sid = _session(store)
        marking_seeds = self._mark(store, sid)
        seeds = marking_seeds(store, sid, store.list_embryos(sid))
        # Scaled by the DIC frame's width over the preview's: 9 / 3.
        assert seeds == {"A_embryo_1": (3.0, 1.5), "ref-2_embryo_2": (7.5, 4.5)}
        # The mark near no embryo is nobody's; a session without a marking has none.
        assert marking_seeds(store, "s9", []) == {} if store.get_session("s9") is None else True

    def test_the_export_cuts_the_embryos_out_when_it_can(self, store, monkeypatch):
        from gently.core import export as export_mod

        sid = _session(store)
        self._mark(store, sid)
        # The fixture's frames are blank, so the boxes are stood in for.
        monkeypatch.setattr(
            export_mod,
            "find_embryo_boxes",
            lambda d, seeds, **kw: {name: (0, 0, 8, 6) for name in seeds},
        )
        seen = []
        out = export_session(store, sid, progress=lambda d, t, w: seen.append((d, t, w)))
        emb = out / "dic" / "embryos"
        assert (emb / "README.md").is_file()
        assert sorted(p.name for p in emb.iterdir() if p.is_dir()) == [
            "A_embryo_1",
            "ref-2_embryo_2",
        ]
        assert len(list((emb / "A_embryo_1" / "raw").glob("*.tif"))) == 2
        assert seen[-1][0] == seen[-1][1] and any(w.startswith("embryos") for _, _, w in seen)
        assert "dic/embryos/<embryo>/" in (out / "README.txt").read_text(encoding="utf-8")

    def test_without_a_marking_or_when_asked_not_to_it_does_not(self, store):
        sid = _session(store)
        out = export_session(store, sid)
        assert not (out / "dic" / "embryos").exists()
        self._mark(store, sid)
        out = export_session(store, sid, crops=False)
        assert not (out / "dic" / "embryos").exists()

    def test_the_route_passes_the_choice_on(self, store, monkeypatch):
        import time

        sid = _session(store)
        self._mark(store, sid)
        c = _client(store)
        c.post(f"/api/sessions/{sid}/export", json={"crops": False})
        for _ in range(100):
            job = c.get(f"/api/sessions/{sid}/export").json()
            if job["state"] != "running":
                break
            time.sleep(0.05)
        assert job["state"] == "done" and not (Path(job["path"]) / "dic" / "embryos").exists()

    def test_the_button_cuts_an_existing_export(self, store, monkeypatch):
        import time

        from gently.core import export as export_mod

        monkeypatch.setattr(sessions_routes, "_MOVIES", {"state": "idle"})
        monkeypatch.setattr(
            export_mod,
            "find_embryo_boxes",
            lambda d, seeds, **kw: {name: (0, 0, 8, 6) for name in seeds},
        )
        sid = _session(store)
        out = export_session(store, sid, crops=False)
        c = _client(store)
        # Without a marking there is nothing to say where the embryos are.
        r = c.post("/api/movies", json={"kind": "crops", "folder": str(out), "session_id": sid})
        assert r.status_code == 409
        self._mark(store, sid)
        r = c.post("/api/movies", json={"kind": "crops", "folder": str(out), "session_id": sid})
        assert r.status_code == 200, r.text
        for _ in range(200):
            job = c.get("/api/movies").json()
            if job["state"] != "running":
                break
            time.sleep(0.05)
        assert job["state"] == "done" and job["outputs"] == ["embryos"], job
        assert (out / "dic" / "embryos" / "A_embryo_1" / "metadata.csv").is_file()
        r = c.post("/api/movies", json={"kind": "crops", "folder": str(out)})
        assert r.status_code == 400

    def test_the_page_offers_it(self):
        for needle in (
            "askMovie('crops')",
            "session-export-crops",
            "Hugging Face",
            "body.session_id",
        ):
            assert needle in REVIEW_JS, needle


class TestTwoFields:
    """ "i am sure two positions exist which covers all the embryos": the
    overview taken from two positions exports as two series, a folder each."""

    @staticmethod
    def _two_field_session(store, sid="two"):
        import tifffile

        store.create_session(sid, name="two fields")
        store.register_embryo(sid, "embryo_1", position_x=-500.0, position_y=-400.0, role="test")
        sd = store._session_dir(sid)
        ref = sd / "calibration" / "brightfield" / "20261004_210000"
        ref.mkdir(parents=True)
        tifffile.imwrite(ref / "dark.tif", np.full((16, 20), 10, dtype=np.uint16))
        tifffile.imwrite(ref / "flat.tif", np.full((16, 20), 500, dtype=np.uint16))
        (ref / "brightfield.yaml").write_text(
            yaml.safe_dump(
                {
                    "record": "20261004_210000",
                    "spec": {"light": "room"},
                    "dark": {"file": "dark.tif"},
                    "flat": {"file": "flat.tif"},
                }
            ),
            encoding="utf-8",
        )
        positions = {1: {"x": -500.0, "y": -400.0}, 2: {"x": 900.0, "y": -400.0}}
        for frame in (1, 2, 3):
            for field in (1, 2):
                store.put_snapshot(
                    sid,
                    "dic",
                    np.full((16, 20), 100 + 50 * field, dtype=np.uint16),
                    metadata={
                        "channel": "dic",
                        "frame": frame,
                        "field": field,
                        "fields": 2,
                        "captured_at": f"2026-10-04T21:{frame:02d}:{field:02d}",
                        "position": positions[field],
                    },
                )
        return sid

    def test_one_folder_per_field_each_a_series_of_its_own(self, store):
        from gently.core.export import _dic_frames

        sid = self._two_field_session(store)
        out = export_session(store, sid)
        d = out / "dic"
        assert not list(d.glob("dic_f*.tif")), "no frames loose in dic/ when there are fields"
        for field in (1, 2):
            fd = d / f"field_{field}"
            names = sorted(p.name for p in fd.glob("dic_f*.tif"))
            assert names == [f"dic_f000{i}_20261004-210{i}0{field}.tif" for i in (1, 2, 3)]
            rows = list(csv.DictReader(open(fd / "dic.csv", encoding="utf-8")))
            assert [r["field"] for r in rows] == ["2", "2", "2"] if field == 2 else True
            assert rows[0]["file"] == f"dic/field_{field}/{names[0]}"
            assert rows[0]["dark"].startswith("../references/")
            # The references resolve from the field folder, so a corrected
            # movie comes out of it like any dic/ folder.
            frames = _dic_frames(fd)
            assert (fd / frames[0]["dark"]).resolve().is_file()
            assert (fd / "dic.avi").is_file() and (fd / "dic_corrected.avi").is_file()
        text = (out / "README.txt").read_text(encoding="utf-8")
        assert "taken from 2 positions" in text and "dic/field_2/" in text

    def test_one_marking_places_the_embryos_in_every_field(self, store):
        """The marking was made at one place; a field is another. The marks
        say how microns map to pixels, and each embryo's own stage position
        is projected into the field. One outside it is left out."""
        from gently.core.export import marking_seeds

        sid = self._two_field_session(store)
        store.register_embryo(sid, "embryo_2", position_x=-600.0, position_y=-320.0, role="test")
        # Preview 5 x 4 at downsample 4 (the frames are 20 x 16), marked at
        # stage (-500, -400): embryo_1 at (-500, -400) sits at pixel (2, 2),
        # embryo_2 at (-600, -320) at pixel (1, 3): 0.01 px/µm in x, 0.0125 in y.
        store.put_snapshot(
            sid,
            "operate_marked",
            np.zeros((4, 5), dtype=np.uint16),
            metadata={
                "kind": "operate_marking",
                "stage_position": [-500.0, -400.0],
                "frame": {"width": 5.0, "height": 4.0, "downsample": 4.0},
                "embryos": [
                    {"pixel_x": 2.0, "pixel_y": 2.0, "stage_x_um": -500.0, "stage_y_um": -400.0},
                    {"pixel_x": 1.0, "pixel_y": 3.0, "stage_x_um": -600.0, "stage_y_um": -320.0},
                ],
            },
        )
        embryos = store.list_embryos(sid)
        # The marking's own field: as marked, scaled by 4.
        assert marking_seeds(store, sid, embryos) == {
            "embryo_1": (8.0, 8.0),
            "embryo_2": (4.0, 12.0),
        }
        # A field 80 µm further in y: both move a pixel (0.0125 px/µm), and
        # embryo_2 at preview row 4 falls off the bottom of a 4-row field.
        assert marking_seeds(store, sid, embryos, position={"x": -500.0, "y": -480.0}) == {
            "embryo_1": (8.0, 12.0)
        }
        # A field far away holds nobody.
        assert marking_seeds(store, sid, embryos, position={"x": 5000.0, "y": 0.0}) == {}
