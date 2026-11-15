"""Side A and side B are brought onto one another by the stage, safely.

"is there a way to automate this?" ... "for safely doing it -- how we do it
only when embryo are known to be there" ... "once aligned we update the xy in
the embryo xy positions".

The operator aligns the two light-sheet views by eye: Multi shows A red over
B green, and the stage is jogged until they overlap. This measures the gap
between where the embryo sits in the two frames and moves the stage to close
it. It moves a real stage under a real objective, so most of what is pinned
here is when it does NOT move.

The rig below is a stand-in: two views of one textured blob, each moving its
own way when the stage moves, as the two arms do.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

from gently.app import ab_align
from gently.core import ab_alignment as ab

pytest.importorskip("scipy")

SHAPE = (256, 512)
RNG = np.random.default_rng(7)
TEXTURE = RNG.random((60, 90)).astype(np.float32)

# Pixels a view's picture moves per um of stage: X slides the two views
# opposite ways along the columns, Y slides both the same way along the rows.
VIEW = {"A": np.array([[0.0, 6.0], [6.0, 0.0]]), "B": np.array([[0.0, 6.0], [-6.0, 0.0]])}
FIT = {"galvo_center": 0.1, "galvo_amplitude": 0.4, "piezo_center": 5.0, "piezo_amplitude": 30.0}
HOME = (100.0, -200.0)


class Rig:
    def __init__(self, gap_cols=40, dark=(), response=None, stuck=False):
        self.at = np.array(HOME)
        self.gap_cols, self.dark, self.stuck = gap_cols, set(dark), stuck
        self.response = response or VIEW
        self.moves: list[tuple[float, float]] = []
        self.looks = 0

    async def get_stage_position(self):
        return tuple(self.at)

    async def move_to_position(self, x, y):
        self.moves.append((x, y))
        if not self.stuck:
            self.at = np.array([x, y])
        return {"success": True}

    async def acquire_volume(self, side="A", **_):
        self.looks += 1
        frame = np.full(SHAPE, 100.0, np.float32) + RNG.normal(0, 1, SHAPE).astype(np.float32)
        if side not in self.dark:
            half = self.gap_cols / 2
            centre = np.array([128.0, 256.0 + (half if side == "A" else -half)])
            row, col = np.round(centre + self.response[side] @ (self.at - np.array(HOME))).astype(
                int
            )
            frame[row - 30 : row + 30, col - 45 : col + 45] += 150 + 60 * TEXTURE
        return {"success": True, "volume": frame[None]}


def _embryo(**over):
    base = {
        "id": "embryo_1",
        "calibration": {**FIT, "B": dict(FIT)},
        "num_slices": 50,
        "exposure_ms": 10.0,
        "position_coarse": {"x": HOME[0], "y": HOME[1]},
        "stage_position": {"x": HOME[0], "y": HOME[1]},
    }
    return SimpleNamespace(**{**base, **over})


@pytest.fixture(autouse=True)
def _small_frames(monkeypatch):
    # The stand-in's frames are a quarter the size of the camera's.
    monkeypatch.setattr(ab, "MIN_AREA_PX", 1500)


def _run(rig, embryo=None, **kw):
    return asyncio.run(ab_align.align_embryo(rig, embryo or _embryo(), **kw))


# ── it closes the gap ─────────────────────────────────────────────────────


def test_it_brings_the_two_views_together_and_says_where_the_stage_is():
    rig = Rig(gap_cols=40)
    out = _run(rig)
    assert out["ok"] and out["aligned"], out["says"]
    assert np.hypot(*out["gap_after_um"]) < 1.0 < np.hypot(*out["gap_um"])
    # 40 px apart, each um of X closing 12: the stage went 3.3 um in X only.
    assert out["moved_um"][0] == pytest.approx(-40 / 12, abs=0.2)
    assert abs(out["moved_um"][1]) < 0.2
    assert out["position"] == {"x": pytest.approx(rig.at[0]), "y": pytest.approx(rig.at[1])}


def test_the_stages_effect_is_measured_by_a_probe_each_way():
    rig = Rig()
    _run(rig)
    probe_x, probe_y, final = rig.moves
    assert probe_x == (HOME[0] + ab_align.PROBE_UM, HOME[1])
    assert probe_y == (HOME[0], HOME[1] + ab_align.PROBE_UM)
    assert np.hypot(final[0] - HOME[0], final[1] - HOME[1]) <= ab_align.MAX_MOVE_UM


def test_measuring_alone_moves_nothing():
    rig = Rig()
    out = _run(rig, move=False)
    assert out["ok"] and not out["aligned"] and rig.moves == []
    assert "Nothing moved" in out["says"]


def test_views_already_together_are_left_alone():
    rig = Rig(gap_cols=2)
    out = _run(rig)
    assert out["aligned"] and rig.moves == [] and "Already aligned" in out["says"]


# ── when it does not move ─────────────────────────────────────────────────


@pytest.mark.parametrize("side", ["A", "B"])
def test_no_fit_on_a_side_and_nothing_is_even_looked_at(side):
    cal = {"B": dict(FIT)} if side == "A" else dict(FIT)
    rig = Rig()
    out = _run(rig, _embryo(calibration=cal))
    assert not out["ok"] and f"no side {side} fit" in out["says"]
    assert rig.moves == [] and rig.looks == 0


def test_the_stage_must_be_at_the_embryo():
    rig = Rig()
    out = _run(rig, _embryo(stage_position={"x": 400.0, "y": -200.0}))
    assert not out["ok"] and "not at this embryo" in out["says"]
    assert rig.moves == [] and rig.looks == 0


@pytest.mark.parametrize("side", ["A", "B"])
def test_a_side_with_nothing_in_it_ends_it_before_any_move(side):
    rig = Rig(dark=[side])
    out = _run(rig)
    assert not out["ok"] and f"Side {side} shows no embryo" in out["says"]
    assert rig.moves == []


def test_a_gap_bigger_than_an_embryo_is_not_believed(monkeypatch):
    monkeypatch.setattr(ab_align, "MAX_GAP_UM", 5.0)
    rig = Rig(gap_cols=60)  # 9.75 um
    out = _run(rig)
    assert not out["ok"] and "Not believed" in out["says"] and rig.moves == []


def test_a_correction_longer_than_the_cap_is_refused_and_the_stage_goes_back(monkeypatch):
    monkeypatch.setattr(ab_align, "MAX_MOVE_UM", 2.0)
    rig = Rig(gap_cols=40)  # needs 3.3 um
    out = _run(rig)
    assert not out["ok"] and "more than the 2 um allowed" in out["says"]
    assert rig.moves[-1] == HOME and tuple(rig.at) == HOME


def test_a_stage_that_moves_both_views_alike_cannot_align_them():
    rig = Rig(response={"A": VIEW["A"], "B": VIEW["A"]})
    out = _run(rig)
    assert not out["ok"] and "cannot bring them together" in out["says"]
    assert tuple(rig.at) == HOME


def test_a_move_that_does_not_help_is_undone():
    rig = Rig(stuck=True)  # the stage reports success and does not move
    out = _run(rig)
    assert not out["ok"] and not out["aligned"]
    assert rig.moves[-1] == HOME
    assert "back where it started" in out["says"]


# ── the measuring ─────────────────────────────────────────────────────────


def test_a_frame_of_noise_stripes_or_nothing_holds_no_embryo():
    noise = RNG.normal(105, 12, SHAPE)
    stripes = 100 + 8 * RNG.normal(size=(1, SHAPE[1])) * np.ones(SHAPE) + RNG.normal(0, 5, SHAPE)
    for frame in (noise, stripes, np.full(SHAPE, 100.0)):
        assert ab.find_object(frame)["found"] is False


def test_a_probe_is_read_from_the_embryos_outline_not_the_frames_texture():
    """On the rig both cameras carry fixed stripes that do not move with the
    stage. A match of whole frames locked onto them: every probe read as no
    shift at all, and the routine refused. The outline moves with the embryo."""
    rig = Rig()
    stripes = 40 * RNG.normal(size=(1, SHAPE[1])).astype(np.float32)
    real = rig.acquire_volume

    async def striped(side="A", **kw):
        r = await real(side=side, **kw)
        r["volume"] = r["volume"] + stripes
        return r

    rig.acquire_volume = striped
    out = _run(rig)
    assert out["aligned"], out["says"]
    assert abs(out["response_px_per_um"]["A"][1][0]) > 4  # the probe was seen


def test_what_the_stage_cannot_close_is_left_out_of_the_move_and_said():
    plan = ab.solve((30.0, 40.0), VIEW["A"], VIEW["B"], 30.0)
    assert plan["ok"] and plan["closes"] == 1
    assert plan["move_um"] == pytest.approx((-40 / 12, 0.0), abs=1e-6)
    assert plan["left_px"] == pytest.approx((30.0, 0.0), abs=1e-6)
