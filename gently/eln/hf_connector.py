"""Approval-gated HuggingFace export connector for the ELN.

Formats accumulated {image ref, model prediction, human ground truth, provenance,
strain} into dataset rows and pushes them to a HuggingFace dataset repo (default
``pskeshu/gently-perception-benchmark``). Design constraints (ELN spine spec):

- **Approval-gated:** the CALLER (a ``require_control`` route + explicit human
  confirm) decides to push; this module never auto-pushes.
- **Token from env** ``HF_TOKEN`` (assumed present in production). Absent → a clear
  ``HFExportError``, never a silent failure.
- **Per-experiment target:** repo / split / revision are parameters.
- ``build_records`` is pure (no I/O) so it is fully unit-testable; the actual push
  lazily imports ``datasets`` (not a base dependency) and accepts an injected
  ``_push_fn`` for tests.
"""

from __future__ import annotations

import os

DEFAULT_REPO = "pskeshu/gently-perception-benchmark"


class HFExportError(RuntimeError):
    """Raised when an export cannot proceed (no token, no records, push failure)."""


def hf_token() -> str | None:
    """The HuggingFace token from the environment, or None."""
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")


def token_present() -> bool:
    return bool(hf_token())


def build_records(annotations: list[dict]) -> list[dict]:
    """Format annotation rows into flat, HF-ready dataset rows. Pure/no-I/O.

    Each input row carries the model prediction + the human ground truth + enough
    provenance to trace back to the session/embryo/annotator (and strain).
    """
    rows = []
    for a in annotations:
        rows.append(
            {
                "session_id": a.get("session_id"),
                "embryo_id": a.get("embryo_id"),
                "image_ref": a.get("image_ref"),
                "predicted_stage": a.get("predicted_stage"),
                "ground_truth_stage": a.get("ground_truth_stage") or a.get("stage"),
                "start_timepoint": a.get("start_timepoint"),
                "end_timepoint": a.get("end_timepoint"),
                "annotator": a.get("annotator"),
                "strain": a.get("strain"),
                "provenance": a.get("provenance") or {},
            }
        )
    return rows


def push_dataset(
    records: list[dict],
    repo: str = DEFAULT_REPO,
    split: str = "train",
    revision: str | None = None,
    token: str | None = None,
    _push_fn=None,
) -> dict:
    """Push formatted records to a HuggingFace dataset repo.

    APPROVAL-GATED: the caller MUST have obtained human confirmation first — this
    function performs the publish, it does not decide to. ``token`` defaults to the
    env ``HF_TOKEN``. ``_push_fn`` is a test injection point. Returns a summary;
    raises ``HFExportError`` on no token / no records / push failure.
    """
    token = token or hf_token()
    if not token:
        raise HFExportError(
            "HF_TOKEN not set — set it in the environment to enable HuggingFace export."
        )
    if not records:
        raise HFExportError("no annotated records to export.")
    if _push_fn is not None:
        _push_fn(records, repo, split, revision, token)
    else:
        try:
            from datasets import Dataset  # lazy — not a base dependency
        except ImportError as e:
            raise HFExportError(
                "the 'datasets' package is required for HuggingFace export "
                "(pip install datasets huggingface_hub)."
            ) from e
        ds = Dataset.from_list(records)
        ds.push_to_hub(repo, split=split, revision=revision, token=token)
    return {"repo": repo, "split": split, "n": len(records), "revision": revision}
