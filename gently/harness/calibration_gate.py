"""Has this embryo actually been calibrated?

One predicate, used by the run routes and by `acquire_volume`, so the answer
cannot differ between the surface an operator drives and the tool an agent
calls.

WHY THIS EXISTS

Nothing checked. `POST /api/devices/timelapse/start` validated
`interval_seconds > 0` and that the embryo ids existed, and started. And the
acquisition layer did not fail on an uncalibrated embryo either — it invented a
complete set of scan geometry, with the comment saying so:

    # Get calibration parameters (use defaults if not calibrated)
    galvo_amplitude = cal.get("galvo_amplitude", 0.5)
    galvo_center    = cal.get("galvo_center", 0.0)
    piezo_amplitude = cal.get("piezo_amplitude", 25.0)
    piezo_center    = cal.get("piezo_center", 50.0)
    slope           = cal.get("slope_um_per_deg", 100.0)

So a timelapse could run to completion on embryos that had never been
calibrated, using five made-up numbers, and report success. The data looks
exactly like real data. That is worse than a refusal, because a refusal is
noticed.

It also inverted the order the team stated out loud on 2026-08-07 — the
operator: "the main thing is just making sure that we can get the calibration
to work"; the PI: "Calibration has to work. Embryo navigation has to work. Then
timelapse setup has to work." The workflow has a hard dependency; now the code
has one too.

WHAT COUNTS AS CALIBRATED

A finite `slope_um_per_deg` in `embryo.calibration`. Every successful fit
writes it (`calibration_tools.py:891`), and it is the number the scan geometry
is derived from — without it there is nothing to derive from but a guess.

Fit *quality* is deliberately not judged here. `r_squared` is hardcoded to 0.85
on the vision-guided path, so it is not currently a measurement, and inventing
a threshold against a literal would be theatre. Presence is checked; quality is
reported for the operator to judge.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# The one field that means a fit happened.
FIT_KEY = "slope_um_per_deg"


def is_calibrated(embryo: Any, side: str = "A") -> bool:
    """True when this embryo carries a usable galvo→piezo fit on `side`.

    Side A is the embryo's calibration; side B is its ``calibration["B"]``
    (the other scanner and piezo's own numbers).
    """
    cal = getattr(embryo, "calibration", None) or {}
    if side == "B" and isinstance(cal, dict):
        cal = cal.get("B") or {}
    if not isinstance(cal, dict):
        return False
    slope = cal.get(FIT_KEY)
    try:
        value = float(slope)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    # A zero slope is not a calibration either: the scan would have no extent.
    return value == value and value not in (float("inf"), float("-inf")) and value != 0.0


def uncalibrated(
    embryos: dict[str, Any], embryo_ids: list[str] | None, sides: Sequence[str] = ("A",)
) -> list[str]:
    """Which of `embryo_ids` have no fit. `None` means every known embryo.

    `sides` is the sides the run images: a two-view run needs a fit on each.
    It used to be judged on side A alone, and the run then left side B out for
    that embryo with a line in the log. An embryo missing only side B is named
    with it ("e2 (side B)"), since it shows a fit everywhere else.

    Unknown ids are not reported here — the routes already reject those, and
    conflating "does not exist" with "not calibrated" would send an operator
    to the wrong fix.
    """
    ids = list(embryo_ids) if embryo_ids else list(embryos.keys())
    out = []
    for eid in ids:
        if eid not in embryos:
            continue
        missing = [s for s in (sides or ("A",)) if not is_calibrated(embryos[eid], s)]
        if missing:
            out.append(f"{eid} (side B)" if missing == ["B"] else eid)
    return out


def refusal_detail(missing: list[str]) -> str:
    """The message an operator gets, naming the embryos and the way past it."""
    names = ", ".join(missing)
    return (
        f"not calibrated: {names}. "
        "An uncalibrated embryo has no galvo/piezo fit, so the scan geometry "
        "would be invented rather than measured. Calibrate them, or pass "
        "allow_uncalibrated=true to acquire anyway and accept that the volume "
        "geometry is a guess."
    )
