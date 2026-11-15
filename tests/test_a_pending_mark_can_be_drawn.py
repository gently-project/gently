"""A mark placed by clicking the picture is drawn.

The XY lock went on 2026-11-08, and `const locked = isEngaged()` went with it
out of drawMarkers. Two lines further down went on reading `locked`, to draw
a pending mark greyed and dashed while the lock was engaged. So drawing the
first pending mark threw a ReferenceError: the click put the mark in the list
and then died before the count was published, the panel went on saying
nothing was marked, and every camera frame after it threw again from the
redraw.

Nothing in CI runs this file's code (it drives no browser, and operate.js is
all DOM), so it was found five days later, on the simulated rig, by clicking
the picture. This pins the one slip. What would catch the next one is a pass
over static/js for names nothing defines (ESLint's no-undef); that is not in
CI yet.
"""

from __future__ import annotations

import re
from pathlib import Path

OPERATE = (
    Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js" / "operate.js"
).read_text(encoding="utf-8")


def _code(body: str) -> str:
    return "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("//"))


def test_drawing_the_marks_reads_nothing_the_xy_lock_left_behind() -> None:
    fn = OPERATE[OPERATE.index("    function drawMarkers() {") :]
    fn = fn[: fn.index("\n    }")]
    assert not re.search(r"\blocked\b", _code(fn)), (
        "drawMarkers reads a variable that does not exist"
    )


def test_nothing_else_of_the_lock_is_read_either() -> None:
    code = _code(OPERATE)
    for gone in ("isEngaged", "ENGAGED_WITHIN_UM", "_headLowered", "renderLock"):
        assert gone not in code, gone
