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
