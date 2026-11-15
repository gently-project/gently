"""Aligning side A and side B on one embryo, with the stage.

The measuring is ``gently.core.ab_alignment``. This is the part that takes
frames and moves the stage, and everything here is about not moving it when
it should not move:

* it runs only for an embryo that has a fit on BOTH sides (each side found
  and focused something here) with the stage at that embryo;
* each side's frame must hold one embryo-sized object, the two of about the
  same size, before anything moves; a dark or empty frame ends it there;
* the gap must be smaller than an embryo: a bigger answer is a wrong answer,
  not a big move;
* the stage's effect is measured, not assumed, by a small probe in X and in
  Y, and each probe must be read cleanly in both views;
* the move is capped, and checked afterwards: if the object is gone from a
  view or the gap did not shrink, the stage goes back to where it started.

Every return path leaves the stage either at the aligned position or back
where it began. ``moves`` in the result is every position the stage was sent
to, in order.

It takes volumes with the embryo's own settings, one per side per look, so a
full alignment costs four looks: the dose of four timepoints.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from gently.core import ab_alignment as ab
from gently.core.coordinates import SPIM_PIXEL_SIZE_UM

logger = logging.getLogger(__name__)

PROBE_UM = 5.0  # the probe: far enough to read to a pixel, well inside the field
MAX_MOVE_UM = 30.0  # the correction's cap
MAX_GAP_UM = 60.0  # about an embryo: a bigger gap is not believed
AT_EMBRYO_UM = 5.0  # how near its recorded position the stage must be
# About 2 um. Three still readings of one embryo on the rig gave 1.1, 0.8 and
# 2.8 um: closer than this is as aligned as a reading can tell.
DONE_PX = 12.0


def _side_fit(calibration: dict | None, side: str) -> dict:
    cal = calibration or {}
    return (cal.get("B") or {}) if side == "B" else cal


def _has_scan(fit: dict) -> bool:
    return all(
        fit.get(k) is not None
        for k in ("galvo_center", "galvo_amplitude", "piezo_center", "piezo_amplitude")
    )


async def _look(client, embryo, side: str) -> np.ndarray | None:
    """One volume from one side, with the embryo's own settings, as a frame."""
    fit = _side_fit(embryo.calibration, side)
    r = await client.acquire_volume(
        num_slices=int(embryo.num_slices or 50),
        exposure_ms=float(embryo.exposure_ms or 10.0),
        galvo_amplitude=float(fit["galvo_amplitude"]),
        galvo_center=float(fit["galvo_center"]),
        piezo_amplitude=float(fit["piezo_amplitude"]),
        piezo_center=float(fit["piezo_center"]),
        side=side,
    )
    if not r.get("success") or r.get("volume") is None:
        return None
    return ab.projection(np.asarray(r["volume"]))


async def align_embryo(client, embryo, *, move: bool = True) -> dict[str, Any]:
    """Measure the A/B gap on ``embryo`` and, if ``move``, close it.

    Returns {ok, aligned, says, gap_um (before), gap_after_um, position
    (where the stage is left), moves}. ``ok`` is False when it declined or
    failed, and ``says`` is why, in the operator's words.
    """
    out: dict[str, Any] = {"ok": False, "aligned": False, "moves": [], "embryo_id": embryo.id}

    def stop(why: str) -> dict[str, Any]:
        out["says"] = why
        logger.info("[ab-align] %s: %s", embryo.id, why)
        return out

    for side in ("A", "B"):
        if not _has_scan(_side_fit(embryo.calibration, side)):
            return stop(f"Embryo has no side {side} fit. Calibrate side {side} first.")
    pos = getattr(embryo, "stage_position", None) or embryo.position_coarse or {}
    x0, y0 = (float(v) for v in await client.get_stage_position())
    out["position"] = {"x": x0, "y": y0}
    if pos.get("x") is None or np.hypot(x0 - float(pos["x"]), y0 - float(pos["y"])) > AT_EMBRYO_UM:
        return stop("The stage is not at this embryo. Centre on it first.")

    async def both() -> tuple[dict, dict, np.ndarray, np.ndarray] | str:
        frames = {}
        for side in ("A", "B"):
            frame = await _look(client, embryo, side)
            if frame is None:
                return f"No frame came from side {side}."
            frames[side] = frame
        a, b = ab.find_object(frames["A"]), ab.find_object(frames["B"])
        for side, found in (("A", a), ("B", b)):
            if not found["found"]:
                return f"Side {side} shows no embryo: {found['why']}. Is the laser on?"
            if found["clipped"]:
                return f"Side {side} has the embryo cut by the edge of its frame."
        if not 0.5 < a["area"] / b["area"] < 2.0:
            return "The two sides do not show the same thing: one object is twice the other's size."
        return a, b, frames["A"], frames["B"]

    async def go(x: float, y: float) -> bool:
        out["moves"].append({"x": round(x, 2), "y": round(y, 2)})
        r = await client.move_to_position(x, y)
        return bool(r.get("success"))

    async def back(why: str) -> dict[str, Any]:
        await go(x0, y0)
        out["position"] = {"x": x0, "y": y0}
        return stop(f"{why} The stage is back where it started.")

    seen = await both()
    if isinstance(seen, str):
        return stop(seen)
    a0, b0 = seen[0], seen[1]
    gap0 = ab.gap(a0, b0)
    out["gap_um"] = [round(g * SPIM_PIXEL_SIZE_UM, 2) for g in gap0]
    if np.hypot(*gap0) * SPIM_PIXEL_SIZE_UM > MAX_GAP_UM:
        return stop(
            f"The two views are {np.hypot(*out['gap_um']):.0f} um apart, more than an embryo. "
            "Not believed, nothing moved."
        )
    if np.hypot(*gap0) <= DONE_PX:
        out.update(ok=True, aligned=True, gap_after_um=out["gap_um"])
        return stop("Already aligned: the two views are within 2 um.")
    if not move:
        out["ok"] = True
        return stop(f"The two views are {np.hypot(*out['gap_um']):.1f} um apart. Nothing moved.")

    # What a stage move does to each view: measured, by a probe each way.
    response = {"A": np.zeros((2, 2)), "B": np.zeros((2, 2))}
    for axis, (dx, dy) in enumerate(((PROBE_UM, 0.0), (0.0, PROBE_UM))):
        if not await go(x0 + dx, y0 + dy):
            return await back("The stage did not make the probe move.")
        for side, base in (("A", a0), ("B", b0)):
            frame = await _look(client, embryo, side)
            if frame is None:
                return await back(f"No frame came from side {side} during the probe.")
            # The embryo's outline is followed, not the frame's texture: the
            # cameras' fixed stripes do not move with the stage, and a match
            # of whole frames locked onto them and read every probe as zero.
            now = ab.find_object(frame)
            if not now["found"] or now["clipped"] or not 0.7 < now["area"] / base["area"] < 1.4:
                return await back(f"Side {side} lost the embryo during the probe move.")
            rows, cols = ab.gap(now, base)
            response[side][:, axis] = (rows / PROBE_UM, cols / PROBE_UM)
    out["response_px_per_um"] = {k: np.round(v, 2).tolist() for k, v in response.items()}

    plan = ab.solve(gap0, response["A"], response["B"], MAX_MOVE_UM)
    if not plan["ok"]:
        return await back(f"{plan['why'][0].upper()}{plan['why'][1:]}.")
    dx, dy = plan["move_um"]
    if not await go(x0 + dx, y0 + dy):
        return await back("The stage did not make the correcting move.")

    seen = await both()
    if isinstance(seen, str):
        return await back(f"After the move: {seen}")
    gap1 = ab.gap(seen[0], seen[1])
    out["gap_after_um"] = [round(g * SPIM_PIXEL_SIZE_UM, 2) for g in gap1]
    if np.hypot(*gap1) >= np.hypot(*gap0):
        return await back("The move did not bring the views closer.")
    out.update(
        ok=True,
        aligned=True,
        position={"x": x0 + dx, "y": y0 + dy},
        moved_um=[round(dx, 2), round(dy, 2)],
    )
    left = np.hypot(*out["gap_after_um"])
    return stop(
        f"Aligned: the views were {np.hypot(*out['gap_um']):.1f} um apart and are {left:.1f} um "
        f"apart, after a stage move of {dx:+.1f}, {dy:+.1f} um."
        + (
            ""
            if plan["closes"] == 2
            else " The rest is in a direction the stage moves both views alike."
        )
    )
