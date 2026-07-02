"""Tests for the per-embryo HuggingFace export route + annotation-summary."""

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(store):
    from gently.ui.web.auth import require_control
    from gently.ui.web.routes.data import create_router

    app = FastAPI()
    server = MagicMock()
    agent = MagicMock()
    agent.experiment = MagicMock()
    agent.store = store
    agent.session_id = "s1"
    server.agent_bridge.agent = agent
    app.include_router(create_router(server))
    app.dependency_overrides[require_control] = lambda: None
    return TestClient(app)


def _store_with(preds, gt):
    store = MagicMock()
    store.set_ground_truth = MagicMock()   # identifies it as the GT/FileStore
    store.get_predictions.return_value = preds
    store.get_ground_truth.return_value = gt
    return store


_PREDS = [{"timepoint": 1, "predicted_stage": "bean"}, {"timepoint": 6, "predicted_stage": "comma"}]
_GT = [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 10, "annotator": "kesh"}]


def test_export_requires_confirm():
    r = _client(_store_with(_PREDS, _GT)).post("/api/embryos/e1/export", json={"session_id": "s1"})
    assert r.status_code == 400


def test_export_requires_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    r = _client(_store_with(_PREDS, _GT)).post(
        "/api/embryos/e1/export", json={"confirm": True, "session_id": "s1"}
    )
    assert r.status_code == 503


def test_export_no_annotated_timepoints(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "x")
    store = _store_with([{"timepoint": 99, "predicted_stage": "comma"}], _GT)  # tp 99 uncovered
    r = _client(store).post("/api/embryos/e1/export", json={"confirm": True, "session_id": "s1"})
    assert r.status_code == 400


def test_export_success_pushes(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "x")
    from gently.eln import hf_connector

    seen = {}

    def fake_push(records, **kw):
        seen.update(n=len(records), repo=kw.get("repo"))
        return {
            "repo": kw.get("repo"), "split": kw.get("split", "train"),
            "n": len(records), "revision": None,
        }

    monkeypatch.setattr(hf_connector, "push_dataset", fake_push)
    r = _client(_store_with(_PREDS, _GT)).post(
        "/api/embryos/e1/export", json={"confirm": True, "session_id": "s1", "strain": "OH904"}
    )
    assert r.status_code == 200
    assert r.json()["n"] == 2
    assert seen["n"] == 2
    assert seen["repo"] == "pskeshu/gently-perception-benchmark"


def test_annotation_summary_route():
    store = _store_with([{"timepoint": t} for t in (1, 2, 40)], _GT)
    r = _client(store).get("/api/embryos/e1/annotation-summary?session_id=s1")
    assert r.status_code == 200
    assert r.json() == {"n_predictions": 3, "n_annotated": 2}
