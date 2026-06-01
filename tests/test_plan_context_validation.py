from gently.harness.memory.model import (
    ImagingSpec,
    PlanContext,
    PlanItem,
    PlanItemType,
)
from gently.harness.plan_mode.tools.validation import _collect_context_warnings


def _embryo_timelapse_item(plan_context=None):
    return PlanItem(
        id="item-1",
        campaign_id="campaign-1",
        type=PlanItemType.IMAGING,
        title="DiSPIM embryo timelapse",
        imaging_spec=ImagingSpec(
            num_slices=80,
            interval_s=120,
            num_embryos=4,
            sample_prep="Embryos on poly-lysine-coated glass slide",
        ),
        plan_context=plan_context,
    )


def test_dispim_embryo_timelapse_warns_without_focus_safety_context():
    item = _embryo_timelapse_item()
    warnings = _collect_context_warnings(
        "[imaging] 'DiSPIM embryo timelapse'",
        item,
        item.imaging_spec,
    )

    assert any("missing microscope thought context layers" in w for w in warnings)
    assert any("F-drive/head-axis focus finding" in w for w in warnings)


def test_dispim_embryo_timelapse_accepts_explicit_focus_safety_context():
    item = _embryo_timelapse_item(
        PlanContext(
            technical=(
                "Bottom overview XY, F-drive focus finding, "
                "and calibration before timelapse."
            ),
            experimental="Ryan/Brie align F/head axis before acquisition.",
            theoretical="Developmental progression remains interpretable.",
            conceptual="Biologist plans at embryo level while Gently manages DiSPIM details.",
            constraints=[
                "Confirm calibration before lowering the SPIM head toward focus",
                "Avoid overtravel beyond embryo focus toward the glass slide",
            ],
        )
    )

    warnings = _collect_context_warnings(
        "[imaging] 'DiSPIM embryo timelapse'",
        item,
        item.imaging_spec,
    )

    assert warnings == []
