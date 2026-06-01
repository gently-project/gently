import pytest

from benchmarks.structured_plan_replay import run_structured_plan_replay


@pytest.mark.asyncio
async def test_structured_plan_replay_scores_created_plan(tmp_path):
    report = await run_structured_plan_replay(tmp_path)

    assert report["benchmark"] == "structured_plan_replay"
    assert report["passed"] is True
    assert report["tool_calls"] == [
        {
            "name": "create_structured_plan",
            "phases": 2,
            "items": 3,
            "dependencies": 2,
        }
    ]
    assert report["expected_counts"] == report["actual_counts"]
    assert report["actual_counts"] == {
        "campaigns": 1,
        "phases": 2,
        "items": 3,
        "dependencies": 2,
    }
    assert any("Created structured plan" in line for line in report["tool_result_excerpt"])
