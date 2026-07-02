"""Perception accuracy scoring — the ELN flywheel's "Score" step.

Compares gently-perception per-timepoint stage predictions against human-authored
ground truth (range-based: a stage spans [start_timepoint, end_timepoint]) and
produces an ``accuracy`` Result. Pure functions — no I/O — so fully unit-testable.
"""

from __future__ import annotations


def stage_at_timepoint(ground_truth: list[dict], tp: int) -> str | None:
    """The ground-truth stage covering timepoint ``tp``, or None.

    Ground-truth entries are ``{stage, start_timepoint, end_timepoint}`` where
    ``end_timepoint`` None means open-ended (until the next stage / session end).
    When ranges overlap, the latest-starting one wins (the more specific label).
    """
    covering = None
    best_start = -1
    for e in ground_truth:
        s = e.get("start_timepoint")
        if s is None:
            continue
        en = e.get("end_timepoint")
        if tp >= s and (en is None or tp <= en) and s > best_start:
            covering = e.get("stage")
            best_start = s
    return covering


def score_accuracy(predictions: list[dict], ground_truth: list[dict]) -> dict:
    """Per-timepoint predicted-vs-ground-truth comparison.

    ``predictions``: ``[{timepoint, predicted_stage}]``;
    ``ground_truth``: ``[{stage, start_timepoint, end_timepoint}]``.
    Returns ``{n_scored, n_correct, accuracy, unscored, confusion}`` where
    ``unscored`` counts predictions with no ground-truth coverage and ``accuracy``
    is None when nothing could be scored.
    """
    n_correct = 0
    n_scored = 0
    unscored = 0
    confusion: dict[str, int] = {}
    for p in predictions:
        tp = p.get("timepoint")
        pred = p.get("predicted_stage")
        gt = stage_at_timepoint(ground_truth, tp) if tp is not None else None
        if gt is None:
            unscored += 1
            continue
        n_scored += 1
        confusion[f"{gt}|{pred}"] = confusion.get(f"{gt}|{pred}", 0) + 1
        if gt == pred:
            n_correct += 1
    accuracy = (n_correct / n_scored) if n_scored else None
    return {
        "n_scored": n_scored,
        "n_correct": n_correct,
        "accuracy": accuracy,
        "unscored": unscored,
        "confusion": confusion,
    }


def accuracy_result(
    session_id: str,
    embryo_id: str,
    predictions: list[dict],
    ground_truth: list[dict],
    run_id: str | None = None,
    annotator: str | None = None,
) -> dict:
    """Build an ``accuracy`` Result dict (matches the spine Result schema)."""
    score = score_accuracy(predictions, ground_truth)
    return {
        "kind": "accuracy",
        "value": score["accuracy"],
        "table": score,
        "method": "per-timepoint predicted-vs-ground-truth stage",
        "inputs": {
            "session_id": session_id,
            "embryo_id": embryo_id,
            "run_id": run_id,
            "n_predictions": len(predictions),
            "n_ground_truth": len(ground_truth),
        },
        "provenance": {"author": annotator},
        "status": "draft" if score["n_scored"] == 0 else "final",
    }
