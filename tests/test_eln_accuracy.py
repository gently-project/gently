"""Tests for ELN perception accuracy scoring."""

from gently.eln import accuracy as acc


def test_stage_at_timepoint_covers_range():
    gt = [
        {"stage": "bean", "start_timepoint": 0, "end_timepoint": 10},
        {"stage": "comma", "start_timepoint": 11, "end_timepoint": None},  # open-ended
    ]
    assert acc.stage_at_timepoint(gt, 5) == "bean"
    assert acc.stage_at_timepoint(gt, 10) == "bean"
    assert acc.stage_at_timepoint(gt, 11) == "comma"
    assert acc.stage_at_timepoint(gt, 999) == "comma"   # open-ended reaches on


def test_stage_at_timepoint_no_coverage():
    gt = [{"stage": "bean", "start_timepoint": 5, "end_timepoint": 10}]
    assert acc.stage_at_timepoint(gt, 2) is None


def test_score_accuracy_mix():
    preds = [
        {"timepoint": 1, "predicted_stage": "bean"},    # correct
        {"timepoint": 6, "predicted_stage": "comma"},   # wrong (gt bean)
        {"timepoint": 12, "predicted_stage": "comma"},  # correct
        {"timepoint": 50, "predicted_stage": "pretzel"},  # unscored (no gt)
    ]
    gt = [
        {"stage": "bean", "start_timepoint": 0, "end_timepoint": 10},
        {"stage": "comma", "start_timepoint": 11, "end_timepoint": 20},
    ]
    s = acc.score_accuracy(preds, gt)
    assert s["n_scored"] == 3
    assert s["n_correct"] == 2
    assert abs(s["accuracy"] - 2 / 3) < 1e-9
    assert s["unscored"] == 1
    assert s["confusion"]["bean|comma"] == 1


def test_accuracy_result_shape_and_draft_when_unscorable():
    preds = [{"timepoint": 100, "predicted_stage": "comma"}]
    gt = [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 10}]
    r = acc.accuracy_result("s1", "e1", preds, gt, run_id="run7", annotator="kesh")
    assert r["kind"] == "accuracy"
    assert r["value"] is None            # nothing scorable
    assert r["status"] == "draft"
    assert r["inputs"]["run_id"] == "run7"
    assert r["provenance"]["author"] == "kesh"
