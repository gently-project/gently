"""Tests for the per-embryo annotation export service."""

from unittest.mock import MagicMock

from gently.eln import export_service as es


def _store(preds, gt):
    s = MagicMock()
    s.get_predictions.return_value = preds
    s.get_ground_truth.return_value = gt
    return s


def test_collect_pairs_predictions_with_gt_ranges():
    preds = [
        {"timepoint": 1, "predicted_stage": "bean"},
        {"timepoint": 6, "predicted_stage": "comma"},
        {"timepoint": 50, "predicted_stage": "pretzel"},  # no GT → dropped
    ]
    gt = [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 10, "annotator": "kesh"}]
    rows = es.collect_embryo_annotations(_store(preds, gt), "s1", "e1", strain="OH904")
    assert len(rows) == 2                       # only annotated timepoints
    assert rows[0]["ground_truth_stage"] == "bean"
    assert rows[0]["predicted_stage"] == "bean"
    assert rows[1]["predicted_stage"] == "comma"   # tp 6, still in [0,10]
    assert rows[0]["annotator"] == "kesh"
    assert rows[0]["strain"] == "OH904"
    assert rows[0]["stage"] == "bean"           # build_records fallback key


def test_collect_include_unannotated():
    preds = [{"timepoint": 99, "predicted_stage": "comma"}]
    gt = [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 10}]
    assert es.collect_embryo_annotations(_store(preds, gt), "s", "e", annotated_only=False)
    assert es.collect_embryo_annotations(_store(preds, gt), "s", "e", annotated_only=True) == []


def test_pred_stage_from_findings():
    preds = [{"timepoint": 2, "findings": {"stage": "1.5fold"}}]
    gt = [{"stage": "1.5fold", "start_timepoint": 0, "end_timepoint": 10}]
    rows = es.collect_embryo_annotations(_store(preds, gt), "s", "e")
    assert rows[0]["predicted_stage"] == "1.5fold"


def test_annotation_summary():
    preds = [{"timepoint": t, "predicted_stage": "x"} for t in (1, 2, 3, 40)]
    gt = [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 5}]
    s = es.annotation_summary(_store(preds, gt), "s", "e")
    assert s == {"n_predictions": 4, "n_annotated": 3}
