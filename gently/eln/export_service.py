"""Assemble a per-embryo annotated timelapse into HuggingFace-ready rows.

The flywheel's unit is one embryo's timelapse + its ground-truth annotations. This
pairs each prediction timepoint with the ground-truth stage covering it (range-based)
and emits rows ready for ``hf_connector.build_records``. Reads via the FileStore
accessors (``get_predictions`` returns dicts; ``get_ground_truth`` returns entries);
normalizes dict / dataclass / object so it's robust to either.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass

from gently.eln.accuracy import stage_at_timepoint


def _as_dict(x) -> dict:
    if isinstance(x, dict):
        return x
    if is_dataclass(x) and not isinstance(x, type):
        return asdict(x)
    if hasattr(x, "__dict__"):
        return dict(x.__dict__)
    return {}


def _pred_stage(rec: dict):
    findings = rec.get("findings")
    return (
        rec.get("predicted_stage")
        or rec.get("stage")
        or (findings.get("stage") if isinstance(findings, dict) else None)
    )


def _annotator_at(gt: list[dict], tp):
    """The annotator of the ground-truth range covering ``tp`` (latest-start wins)."""
    if tp is None:
        return None
    best = None
    best_start = -1
    for e in gt:
        s = e.get("start_timepoint")
        if s is None:
            continue
        en = e.get("end_timepoint")
        if tp >= s and (en is None or tp <= en) and s > best_start:
            best = e.get("annotator")
            best_start = s
    return best


def collect_embryo_annotations(
    store, session_id: str, embryo_id: str, strain: str | None = None, annotated_only: bool = True
) -> list[dict]:
    """Rows for one embryo's timelapse: each prediction paired with its ground-truth stage.

    ``annotated_only`` keeps only rows that have a human ground-truth label — the export
    payload. Set False to include un-annotated predictions too.
    """
    preds = store.get_predictions(session_id, embryo_id) or []
    gt = [_as_dict(e) for e in (store.get_ground_truth(session_id, embryo_id) or [])]
    rows = []
    for p in preds:
        rec = _as_dict(p)
        tp = rec.get("timepoint")
        gt_stage = stage_at_timepoint(gt, tp) if tp is not None else None
        if annotated_only and gt_stage is None:
            continue
        rows.append(
            {
                "session_id": session_id,
                "embryo_id": embryo_id,
                "timepoint": tp,
                "predicted_stage": _pred_stage(rec),
                "ground_truth_stage": gt_stage,
                "stage": gt_stage,  # hf_connector.build_records falls back to `stage`
                "annotator": _annotator_at(gt, tp),
                "strain": strain,
                "provenance": {
                    "session_id": session_id,
                    "embryo_id": embryo_id,
                    "source": "gently",
                },
            }
        )
    return rows


def annotation_summary(store, session_id: str, embryo_id: str) -> dict:
    """``{n_predictions, n_annotated}`` for the per-embryo push affordance."""
    preds = store.get_predictions(session_id, embryo_id) or []
    gt = [_as_dict(e) for e in (store.get_ground_truth(session_id, embryo_id) or [])]
    n_ann = 0
    for p in preds:
        tp = _as_dict(p).get("timepoint")
        if tp is not None and stage_at_timepoint(gt, tp) is not None:
            n_ann += 1
    return {"n_predictions": len(preds), "n_annotated": n_ann}
