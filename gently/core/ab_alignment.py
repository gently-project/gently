"""Bringing the two light-sheet views onto one another.

Side A and side B look at the sample from two arms. With the sample where
the two optical axes cross, it sits at the same place in both cameras'
frames: the red and green pictures of Multi overlap. The operator does that
by eye, jogging the stage in XY. This measures it, and says what stage move
closes the gap.

Two things, each pure (frames in, numbers out):

* ``find_object``: is there one embryo-sized thing in this frame, and where.
  The two views see the embryo from 90 degrees apart, so their fine structure
  does not match (measured on the first two-sided run: a phase correlation of
  A against B, mirrored any way, peaks no higher than against noise). Their
  outlines do: one blob each, the same size within a few percent. The
  misalignment is the difference of the two centroids.
* ``solve``: from what a probe in X and in Y did to each view's centroid (the
  outline again: the cameras' fixed stripes do not move with the stage, and
  a correlation of whole frames locks onto them), the stage move
  that brings the centroids together, and what no stage move can remove (a
  direction both views shift alike in is the cameras', not the stage's).

Nothing here moves anything; ``gently.app.ab_align`` does, with the gates.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# One embryo fills about 36,000 px of a 512 x 2048 frame at 0.1625 um/px.
MIN_AREA_PX = 4_000
MAX_AREA_FRACTION = 0.4
# How far the blob's peak stands above the background, in the smoothed
# background's own deviations. An embryo measured 125; empty frames reach 5.5.
MIN_CONTRAST = 15.0


def projection(volume: np.ndarray) -> np.ndarray:
    """A volume as the one frame the camera's field is judged on."""
    vol = np.asarray(volume)
    return (vol.max(axis=0) if vol.ndim == 3 else vol).astype(np.float32)


def find_object(frame: np.ndarray) -> dict[str, Any]:
    """The one bright thing in a frame: found or not, its centroid (row, col)
    in pixels, its area, and how far it stands above the background."""
    from scipy import ndimage as ndi

    img = np.asarray(frame, dtype=np.float32)
    smooth = ndi.gaussian_filter(img, 6)
    bg = float(np.median(smooth))
    peak = float(smooth.max())
    # Against the background's own spread (the median deviation), not the
    # frame's: an object raises the frame's deviation with its own size, so a
    # big embryo scored lower than a small one.
    spread = 1.4826 * float(np.median(np.abs(smooth - bg)))
    contrast = (peak - bg) / (spread + 1e-9) if peak > bg else 0.0
    out: dict[str, Any] = {"found": False, "contrast": round(contrast, 2), "why": ""}
    if contrast < MIN_CONTRAST:
        out["why"] = "nothing stands out of the background"
        return out
    labels, n = ndi.label(smooth > bg + 0.35 * (peak - bg))
    if n == 0:
        out["why"] = "nothing stands out of the background"
        return out
    sizes = ndi.sum(np.ones_like(smooth), labels, range(1, n + 1))
    k = int(np.argmax(sizes)) + 1
    area = int(sizes[k - 1])
    out["area"] = area
    if area < MIN_AREA_PX:
        out["why"] = f"the brightest thing is {area} px, too small to be an embryo"
        return out
    if area > MAX_AREA_FRACTION * img.size:
        out["why"] = "the frame is bright all over, not one object"
        return out
    # A second thing nearly as big means the centroid would be of neither.
    if n > 1 and float(np.sort(sizes)[-2]) > 0.5 * area:
        out["why"] = "more than one object in the frame"
        return out
    row, col = ndi.center_of_mass(smooth - bg, labels, k)
    ys, xs = np.nonzero(labels == k)
    out.update(
        found=True,
        centroid=(float(row), float(col)),
        # Cut by the frame's edge, its centroid is of the part that shows.
        clipped=bool(
            ys.min() == 0
            or xs.min() == 0
            or ys.max() == img.shape[0] - 1
            or xs.max() == img.shape[1] - 1
        ),
    )
    return out


def gap(a: dict[str, Any], b: dict[str, Any]) -> tuple[float, float]:
    """Where A's object is relative to B's, in pixels (rows, cols)."""
    return (a["centroid"][0] - b["centroid"][0], a["centroid"][1] - b["centroid"][1])


def solve(
    gap_px: tuple[float, float],
    response_a: np.ndarray,
    response_b: np.ndarray,
    max_move_um: float,
) -> dict[str, Any]:
    """The stage move (dx, dy in um) that closes ``gap_px``.

    ``response_a`` and ``response_b`` are 2x2: pixels of (rows, cols) each
    view's picture moves per um of stage X (first column) and Y (second).
    The gap changes by their difference. A direction the two views move
    alike in is one the stage cannot close: it is left out of the move and
    reported as ``left_px``, what will remain.
    """
    g = np.asarray(gap_px, dtype=float)
    d = np.asarray(response_a, dtype=float) - np.asarray(response_b, dtype=float)
    u, s, vt = np.linalg.svd(d)
    # px of gap closed per um of stage. Under 0.5 px/um a direction would
    # need a long move for a small gain, on a measurement good to a pixel.
    keep = s > 0.5
    if not keep.any():
        return {
            "ok": False,
            "why": "moving the stage shifts both views alike: it cannot bring them together",
        }
    inv = (vt.T[:, keep] / s[keep]) @ u.T[:, keep].T
    move = -(inv @ g)
    asked = float(np.hypot(*move))
    if asked > max_move_um:
        return {
            "ok": False,
            "why": f"it would take a {asked:.0f} um move, "
            f"more than the {max_move_um:.0f} um allowed",
            "move_um": (float(move[0]), float(move[1])),
        }
    left = g + d @ move
    return {
        "ok": True,
        "move_um": (float(move[0]), float(move[1])),
        "left_px": (float(left[0]), float(left[1])),
        "closes": int(keep.sum()),
    }
