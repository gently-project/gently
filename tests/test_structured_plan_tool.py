from types import SimpleNamespace

import pytest

from gently.harness.memory.model import PlanContext, PlanItemType
from gently.harness.tools.registry import get_tool_registry

# Import registers the plan-mode tools with the global registry.
from gently.harness.plan_mode.tools import planning  # noqa: F401


@pytest.mark.asyncio
async def test_create_structured_plan_builds_phases_items_and_dependencies(context_store):
    agent = SimpleNamespace(context_store=context_store)

    result = await get_tool_registry().execute(
        "create_structured_plan",
        {
            "description": "Safe F-drive focus finding",
            "shorthand": "fdrive-focus-2026",
            "target": "Locate embryos and decide whether a safe timelapse can start",
            "phases": [
                {"key": "setup", "description": "Setup and calibration"},
                {"key": "run", "description": "Timelapse readiness"},
            ],
            "items": [
                {
                    "key": "find",
                    "phase": "setup",
                    "type": "imaging",
                    "title": "Locate embryos in XY",
                    "spec": {
                        "sample_prep": "poly-lysine slide",
                        "num_embryos": 3,
                    },
                    "plan_context": {
                        "technical": "Bottom overview camera locates embryos in XY.",
                        "experimental": "Ryan and Brie verify positions before focus approach.",
                        "theoretical": "Embryos remain comparable after mounting.",
                        "conceptual": "Keep microscope support visible to the biologist.",
                        "constraints": ["Avoid overtravel toward glass"],
                    },
                },
                {
                    "key": "calibrate",
                    "phase": "setup",
                    "type": "imaging",
                    "title": "Calibrate galvo-piezo per embryo",
                    "depends_on": ["find"],
                },
                {
                    "key": "decide",
                    "phase": "run",
                    "task_class": "decision_point",
                    "title": "Decide whether to start timelapse",
                    "depends_on": ["calibrate"],
                },
            ],
        },
        {"agent": agent},
    )

    campaign = context_store.resolve_campaign("fdrive-focus-2026")
    assert campaign is not None
    phases = context_store.get_subcampaigns(campaign.id)
    assert [phase.description for phase in phases] == [
        "Setup and calibration",
        "Timelapse readiness",
    ]

    setup_items = context_store.get_plan_items(campaign_id=phases[0].id)
    run_items = context_store.get_plan_items(campaign_id=phases[1].id)
    assert [item.title for item in setup_items] == [
        "Locate embryos in XY",
        "Calibrate galvo-piezo per embryo",
    ]
    assert run_items[0].type == PlanItemType.DECISION_POINT
    assert setup_items[0].type == PlanItemType.IMAGING
    assert isinstance(setup_items[0].plan_context, PlanContext)
    assert setup_items[0].plan_context.constraints == ["Avoid overtravel toward glass"]

    assert context_store.get_plan_item_dependencies(setup_items[1].id) == [setup_items[0].id]
    assert context_store.get_plan_item_dependencies(run_items[0].id) == [setup_items[1].id]
    assert "Created structured plan" in result
    assert "Phases: 2" in result
    assert "Items: 3" in result
    assert "EXPERIMENTAL PLAN" in result
