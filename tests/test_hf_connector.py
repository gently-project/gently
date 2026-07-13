"""Tests for the approval-gated HuggingFace export connector."""

import pytest

from gently.eln import hf_connector as hc


def test_build_records_maps_prediction_and_ground_truth():
    rows = hc.build_records(
        [
            {
                "session_id": "s",
                "embryo_id": "e",
                "predicted_stage": "comma",
                "stage": "bean",
                "start_timepoint": 10,
                "end_timepoint": 20,
                "annotator": "kesh",
                "strain": "OH904",
            }
        ]
    )
    assert rows[0]["ground_truth_stage"] == "bean"  # falls back to `stage`
    assert rows[0]["predicted_stage"] == "comma"
    assert rows[0]["start_timepoint"] == 10
    assert rows[0]["strain"] == "OH904"


def test_push_requires_token(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    with pytest.raises(hc.HFExportError):
        hc.push_dataset([{"a": 1}], token=None)


def test_push_empty_records_raises():
    with pytest.raises(hc.HFExportError):
        hc.push_dataset([], token="x")


def test_push_uses_injected_fn_and_default_repo():
    seen = {}

    def fake(records, repo, split, revision, token):
        seen.update(repo=repo, n=len(records), split=split, token=token)

    out = hc.push_dataset([{"a": 1}, {"a": 2}], split="train", token="tok", _push_fn=fake)
    assert out["n"] == 2
    assert out["repo"] == "pskeshu/gently-perception-benchmark"
    assert seen["n"] == 2 and seen["token"] == "tok"


def test_token_present(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "abc")
    assert hc.token_present() is True
    monkeypatch.delenv("HF_TOKEN")
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    assert hc.token_present() is False
