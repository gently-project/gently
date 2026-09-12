"""The bottom-camera embryo candidate finder must survive the two things that
break a global brightness threshold: a strong low-frequency illumination
gradient (bright corners / diffuse glow) and a resolution that isn't the raw
2048² frame.

The shipping version thresholded the 99th brightness percentile and dilated,
so it fired on the gradient (~1 false positive per real embryo) and, because
its ``min_area`` was hard-coded for the 2048² frame, silently rejected genuine
embryos on the 410 px display frame. These tests pin the fix: flat-fielding +
scale-matched blob detection that auto-scales with image size, keeping only
peaks comparable in strength to the brightest (so compact debris that is far
above the noise, but dimmer than the embryos, is rejected).

Synthetic images only — no dependency on a storage tree or on SAM (candidate
finding never touches the SAM model), so this runs in CI.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np

from gently.hardware.dispim.sam_detection import SAMEmbryoDetector


def _blob(img: np.ndarray, cx: int, cy: int, sigma: float, amp: float) -> None:
    """Add a Gaussian embryo-like blob into ``img`` in place."""
    h, w = img.shape
    ys, xs = np.mgrid[0:h, 0:w]
    img += amp * np.exp(-(((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma**2)))


def _synth_field(maxdim: int, seed: int = 0) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """A bottom-camera-like field: illumination gradient + diffuse glow + heavy
    noise + four bright embryo blobs in the characteristic grid. Returns the
    image and the true blob centres (x, y), scaled to ``maxdim``."""
    rng = np.random.default_rng(seed)
    n = maxdim
    img = np.zeros((n, n), np.float32)

    # Low-frequency illumination gradient (dark one corner, bright the other).
    ys, xs = np.mgrid[0:n, 0:n]
    img += 70.0 * (xs + ys) / (2 * n)
    # A broad diffuse glow in a corner — the classic false-positive trap. Sigma
    # is large (whole-field scale) so a top-hat removes it but a percentile
    # cannot. Kept clear of the embryo grid so it doesn't saturate a real one.
    _blob(img, int(0.85 * n), int(0.15 * n), sigma=0.16 * n, amp=80.0)

    s = maxdim / 410.0
    r = max(3.0, 5.0 * s)  # embryo blob sigma at this resolution
    centres = [
        (int(0.42 * n), int(0.40 * n)),
        (int(0.58 * n), int(0.40 * n)),
        (int(0.42 * n), int(0.55 * n)),
        (int(0.58 * n), int(0.55 * n)),
    ]
    for cx, cy in centres:
        _blob(img, cx, cy, sigma=r, amp=150.0)

    img += rng.normal(0, 22.0, size=img.shape)  # sensor noise
    img = np.clip(img, 0, 255).astype(np.uint8)
    return img, centres


def _detector() -> SAMEmbryoDetector:
    # No API key, no SAM load — find_embryo_candidates is pure image analysis.
    return SAMEmbryoDetector(anthropic_api_key=None)


def _match(cands: list[dict], centres: list[tuple[int, int]], tol: float) -> int:
    """Count true centres that have a candidate centroid within ``tol`` px."""
    hits = 0
    for cx, cy in centres:
        if any(np.hypot(c["centroid"][0] - cx, c["centroid"][1] - cy) <= tol for c in cands):
            hits += 1
    return hits


def test_finds_every_embryo_without_false_positives_on_the_gradient() -> None:
    img, centres = _synth_field(410)
    cands, enhanced = _detector().find_embryo_candidates(img)

    assert _match(cands, centres, tol=16) == len(centres), "missed a planted embryo"
    # Precision: the gradient and the diffuse glow must NOT produce extra
    # candidates. Exactly the four embryos, nothing else.
    assert len(cands) == len(centres), f"false positives: got {len(cands)} candidates"
    # The enhanced image handed to SAM is 8-bit, same frame size.
    assert enhanced.dtype == np.uint8
    assert enhanced.shape == img.shape


def test_the_diffuse_glow_alone_yields_no_candidates() -> None:
    """A field with the gradient + glow but NO embryos must detect nothing —
    this is exactly what the old percentile threshold got wrong."""
    # Same gradient + glow + noise as _synth_field, without the embryo blobs.
    rng = np.random.default_rng(0)
    n = 410
    ys, xs = np.mgrid[0:n, 0:n]
    bg = 70.0 * (xs + ys) / (2 * n)
    _blob(bg, int(0.85 * n), int(0.15 * n), sigma=0.16 * n, amp=80.0)
    bg += rng.normal(0, 22.0, size=bg.shape)
    bg = np.clip(bg, 0, 255).astype(np.uint8)

    cands, _ = _detector().find_embryo_candidates(bg)
    assert cands == [], f"glow produced {len(cands)} phantom embryos"


def test_detection_is_resolution_invariant() -> None:
    """Same scene at 410 px and 2048 px must yield the same embryo count — the
    2048²-only ``min_area`` bug meant the small frame found nothing."""
    small_img, small_c = _synth_field(410, seed=1)
    big_img, big_c = _synth_field(2048, seed=1)
    det = _detector()

    small = det.find_embryo_candidates(small_img)[0]
    big = det.find_embryo_candidates(big_img)[0]

    assert _match(small, small_c, tol=16) == len(small_c)
    assert _match(big, big_c, tol=80) == len(big_c)
    assert len(small) == len(big) == len(small_c)


def _add_debris(img: np.ndarray, maxdim: int, seed: int) -> np.ndarray:
    """Sprinkle compact specks: real structure far above the noise floor, but
    clearly dimmer than the embryos — what over-fired on raw 2048 px frames."""
    rng = np.random.default_rng(seed)
    out = img.astype(np.float32)
    s = maxdim / 410.0
    for _ in range(6):
        # keep clear of the embryo grid (0.42-0.58) and the corner glow
        cx = int(rng.uniform(0.08, 0.30) * maxdim)
        cy = int(rng.uniform(0.10, 0.90) * maxdim)
        _blob(out, cx, cy, sigma=max(2.0, 3.0 * s), amp=60.0)
    return np.clip(out, 0, 255).astype(np.uint8)


def test_dimmer_debris_is_rejected() -> None:
    img, centres = _synth_field(410, seed=3)
    img = _add_debris(img, 410, seed=3)
    cands, _ = _detector().find_embryo_candidates(img)

    assert _match(cands, centres, tol=16) == len(centres)
    assert len(cands) == len(centres), f"debris passed: got {len(cands)} candidates"


def test_dimmer_debris_is_rejected_on_the_raw_frame_too() -> None:
    """The 2048 px path area-downsamples, which lowers the noise and so lifts
    debris far above a noise-relative threshold; it must still be rejected."""
    img, centres = _synth_field(2048, seed=4)
    img = _add_debris(img, 2048, seed=4)
    cands, _ = _detector().find_embryo_candidates(img)

    assert _match(cands, centres, tol=80) == len(centres)
    assert len(cands) == len(centres), f"debris passed: got {len(cands)} candidates"


def test_min_relative_peak_trades_recall_for_precision_monotonically() -> None:
    """Raising min_relative_peak never increases the candidate count."""
    img, _ = _synth_field(410, seed=2)
    img = _add_debris(img, 410, seed=2)
    det = _detector()
    counts = [
        len(det.find_embryo_candidates(img, min_relative_peak=r)[0]) for r in (0.1, 0.3, 0.6, 0.9)
    ]
    assert counts == sorted(counts, reverse=True), counts
    assert counts[0] > counts[2], "a low setting should admit the debris"


def _field_16bit_with_brighter_artifact(maxdim: int = 410, seed: int = 7):
    """A 16-bit field (as the camera delivers) holding four embryos plus one
    compact object ~3x brighter, well clear of the embryo grid.

    16-bit on purpose: in 8-bit the 2-98 percentile stretch saturates every
    bright object to 255, which hides this failure. Real captures have the
    headroom, so the test needs it too.
    """
    rng = np.random.default_rng(seed)
    n = maxdim
    img = np.zeros((n, n), np.float32)
    ys, xs = np.mgrid[0:n, 0:n]
    img += 2000.0 + 26000.0 * (xs + ys) / (2 * n)

    s = maxdim / 410.0
    centres = [
        (int(0.42 * n), int(0.40 * n)),
        (int(0.58 * n), int(0.40 * n)),
        (int(0.42 * n), int(0.55 * n)),
        (int(0.58 * n), int(0.55 * n)),
    ]
    for cx, cy in centres:
        _blob(img, cx, cy, sigma=max(3.0, 5.0 * s), amp=5000.0)
    _blob(img, int(0.18 * n), int(0.80 * n), sigma=max(3.0, 6.0 * s), amp=15000.0)

    img += rng.normal(0, 600.0, size=img.shape)
    return np.clip(img, 0, 65535).astype(np.uint16), centres


def test_a_brighter_artifact_must_not_suppress_the_embryos() -> None:
    """``min_relative_peak`` normalises by the BRIGHTEST peak, so one artifact
    brighter than every embryo collapses their scores and drops them all - a
    silent, total failure of detection. A dust glint or a bubble catching the
    light does this.

    So the review path must not rely on it: it asks for the strongest N peaks
    above the noise floor instead, and lets the classifier reject the junk. On
    real frames the relative rule lost 10 of 16 embryos under this injection.
    """
    img, centres = _field_16bit_with_brighter_artifact()
    det = _detector()

    # The rule being guarded against.
    by_relative, _ = det.find_embryo_candidates(img, min_relative_peak=0.35)
    # What the review path actually asks for: no relative cut, bounded count.
    top_n, _ = det.find_embryo_candidates(img, min_relative_peak=0.0, max_candidates=16)

    assert _match(top_n, centres, tol=16) == len(centres), (
        "top-N proposals must survive a brighter artifact"
    )
    assert _match(by_relative, centres, tol=16) < len(centres), (
        "expected the relative rule to drop embryos here - if it no longer "
        "does, this guard is testing nothing"
    )


def test_the_review_path_does_not_threshold_on_relative_strength() -> None:
    """Pin the wiring, not just the primitive: with the classifier available,
    detect_embryos must propose with no relative cut and a bounded count."""
    import asyncio
    from unittest.mock import patch

    det = _detector()
    # Truthy stand-in: enables the review path without a real client. Cast so
    # both mypy runs agree (the deps-less run sees anthropic as Any).
    det.claude_client = cast(Any, object())

    with patch.object(
        det,
        "find_embryo_candidates",
        return_value=([], np.zeros((410, 410), np.uint8)),
    ) as spy:
        asyncio.run(
            det.detect_embryos(
                np.zeros((410, 410), np.uint8), (0.0, 0.0), save_visualizations=False
            )
        )

    kwargs = spy.call_args.kwargs
    assert kwargs["min_relative_peak"] == 0.0
    assert kwargs["max_candidates"] == SAMEmbryoDetector._REVIEW_MAX_CANDIDATES


def test_max_candidates_bounds_the_work_and_keeps_the_strongest() -> None:
    img, centres = _synth_field(410, seed=8)
    img = _add_debris(img, 410, seed=8)
    det = _detector()

    capped, _ = det.find_embryo_candidates(img, min_relative_peak=0.0, max_candidates=5)
    assert len(capped) <= 5
    # The cap keeps the strongest, so the real embryos must survive it.
    assert _match(capped, centres, tol=16) == len(centres)

    uncapped, _ = det.find_embryo_candidates(img, min_relative_peak=0.0)
    assert len(uncapped) >= len(capped)
    assert min(c["relative_strength"] for c in capped) >= 0.0
