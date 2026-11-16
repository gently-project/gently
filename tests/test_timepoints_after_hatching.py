"""An embryo set to end "at hatching, then N more" is imaged N more times."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from gently.app.orchestration.timelapse import TimelapseOrchestrator
from gently.app.orchestration.timelapse_models import StopCondition
from gently.harness.state import EmbryoState
from gently.organisms import load_organism

load_organism("celegans")  # the stages a stop is named by are the organism's


def _orch(stage: str | None, hatched_flag: bool = False) -> SimpleNamespace:
    """What the check reads: the perceiver's stage and the embryo's own flag."""
    perceiver = MagicMock()
    perceiver.get_session.return_value = SimpleNamespace(current_stage=stage) if stage else None
    embryo = SimpleNamespace(hatching_status={"hatched": hatched_flag})
    experiment = SimpleNamespace(embryos={"embryo_1": embryo})
    return SimpleNamespace(perceiver=perceiver, experiment=experiment, _started_at=None)


def _rounds(orch: SimpleNamespace, cond: StopCondition, first: int, count: int) -> list[bool]:
    state = EmbryoState(id="embryo_1")
    ended = []
    for n in range(first, first + count):
        state.timepoints_acquired = n
        reason = TimelapseOrchestrator._evaluate_single_condition(orch, cond, state)  # type: ignore[arg-type]
        ended.append(reason is not None)
    return ended


def test_perception_seeing_it_hatched_waits_the_timepoints_asked_for() -> None:
    cond = StopCondition.parse("hatching+3")
    # Seen hatched at timepoint 10: imaged at 11, 12 and 13, and ended there.
    assert _rounds(_orch("hatched"), cond, 10, 4) == [False, False, False, True]


def test_the_detectors_flag_waits_them_too() -> None:
    cond = StopCondition.parse("hatching+2")
    assert _rounds(_orch(None, hatched_flag=True), cond, 7, 3) == [False, False, True]


def test_with_none_asked_for_it_ends_when_it_hatches() -> None:
    cond = StopCondition.parse("hatching")
    assert _rounds(_orch("hatched"), cond, 10, 1) == [True]
    assert _rounds(_orch(None, hatched_flag=True), cond, 10, 1) == [True]
    assert _rounds(_orch("comma"), cond, 10, 2) == [False, False]
