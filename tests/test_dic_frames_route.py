"""The DIC overview frames of the live session, listed and rendered.

"in embryos tab the DIC overview image is not viewable … it appears more
like an icon, than a clickable image." The event's thumbnail is for
noticing a frame land; these routes are what a click opens.
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

pytest.importorskip("tifffile")
pytest.importorskip("PIL")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from gently.ui.web.routes.dic import create_router  # noqa: E402


def _frame(tmp_path: Path, n: int, shape=(400, 600)) -> dict:
    import tifffile

    p = tmp_path / "snapshots" / f"dic_frame{n}.tif"
    p.parent.mkdir(parents=True, exist_ok=True)
    arr = (np.arange(shape[0] * shape[1], dtype=np.uint16) % 4096).reshape(shape)
    tifffile.imwrite(str(p), arr)
    return {
        "session_id": "s1",
        "source": "dic",
        "file_path": str(p),
        "captured_at": f"2026-09-26T10:0{n}:00",
        "width": shape[1],
        "height": shape[0],
        "metadata": {
            "channel": "dic",
            "frame": n,
            "round": n * 3,
            "position": {"x": -500.0, "y": -400.0},
        },
    }


def _app(records, session_id="s1"):
    server = MagicMock()
    server.agent_bridge.agent.session_id = session_id
    server.gently_store.list_snapshots = MagicMock(
        side_effect=lambda sid, source=None: [
            r for r in records if sid == "s1" and (source in (None, r["source"]))
        ]
    )
    app = FastAPI()
    app.include_router(create_router(server))
    return TestClient(app), server


def test_the_sessions_frames_are_listed_oldest_first(tmp_path):
    client, server = _app([_frame(tmp_path, 2), _frame(tmp_path, 1)])
    r = client.get("/api/dic/frames")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert [f["frame"] for f in body["frames"]] == [2, 1], "the store's order is kept"
    f = body["frames"][1]
    assert f["stem"] == "dic_frame1" and f["url"] == "/api/dic/frames/dic_frame1.png"
    assert f["round"] == 3 and f["position"] == {"x": -500.0, "y": -400.0}
    server.gently_store.list_snapshots.assert_called_with("s1", "dic")


def test_a_frame_is_rendered_from_the_tiff_as_png(tmp_path):
    client, _ = _app([_frame(tmp_path, 1)])
    r = client.get("/api/dic/frames/dic_frame1.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    im = Image.open(io.BytesIO(r.content))
    assert im.size == (600, 400), "the full frame, not a thumbnail"
    assert "immutable" in r.headers.get("cache-control", "")


def test_max_bounds_the_longer_side_for_a_thumbnail(tmp_path):
    client, _ = _app([_frame(tmp_path, 1)])
    r = client.get("/api/dic/frames/dic_frame1.png?max=200")
    assert r.status_code == 200
    from PIL import Image

    im = Image.open(io.BytesIO(r.content))
    assert max(im.size) <= 200 and min(im.size) > 0


def test_only_frames_the_session_filed_can_be_asked_for(tmp_path):
    # The stem is looked up in the store's listing, never joined to a path.
    client, _ = _app([_frame(tmp_path, 1)])
    assert client.get("/api/dic/frames/dic_frame9.png").status_code == 404
    assert client.get("/api/dic/frames/..%2F..%2Fsecret.png").status_code == 404


def test_a_frame_gone_from_disk_is_404_not_500(tmp_path):
    rec = _frame(tmp_path, 1)
    Path(rec["file_path"]).unlink()
    client, _ = _app([rec])
    assert client.get("/api/dic/frames/dic_frame1.png").status_code == 404


def test_no_session_means_no_frames_not_an_error(tmp_path):
    client, _ = _app([_frame(tmp_path, 1)], session_id=None)
    r = client.get("/api/dic/frames")
    assert r.status_code == 200 and r.json() == {"frames": [], "count": 0}
