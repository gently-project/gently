import pytest

from benchmarks.evaluator import BenchmarkTask, CopilotBenchmarkEvaluator, load_tasks
from benchmarks.mock_client import MockQueueServerClient


def test_default_tasks_cover_required_categories():
    tasks = load_tasks()
    categories = {task.category for task in tasks}

    assert {
        "navigation",
        "acquisition",
        "analysis",
        "multi_step",
        "error_recovery",
    }.issubset(categories)


def test_evaluator_scores_expected_tool_sequence_and_params():
    task = BenchmarkTask(
        id="volume",
        category="acquisition",
        prompt="Acquire a volume of embryo 1.",
        expected_tools=["acquire_volume"],
        expected_params={"acquire_volume": {"embryo_id": "embryo_1"}},
        max_tool_calls=2,
    )
    evaluator = CopilotBenchmarkEvaluator(tasks=[task])

    result = evaluator.evaluate_task(
        task,
        [{"name": "acquire_volume", "input": {"embryo_id": "embryo_1"}}],
    )

    assert result.passed
    assert result.total_score == pytest.approx(1.0)


def test_evaluator_penalizes_missing_tools_and_extra_calls():
    task = BenchmarkTask(
        id="move",
        category="navigation",
        prompt="Move to embryo 2.",
        expected_tools=["move_to_embryo"],
        expected_params={"move_to_embryo": {"embryo_id": "embryo_2"}},
        max_tool_calls=1,
    )
    evaluator = CopilotBenchmarkEvaluator(tasks=[task])

    result = evaluator.evaluate_task(
        task,
        [
            {"name": "get_stage_position", "input": {}},
            {"name": "move_stage", "input": {"x": 100.0, "y": 200.0}},
        ],
    )

    assert not result.passed
    assert result.completion_score == 0.0
    assert result.efficiency_score == 0.5
    assert "missing expected tool: move_to_embryo" in result.errors


def test_evaluator_reports_category_scores():
    tasks = [
        BenchmarkTask("ok", "navigation", "Move", ["move_stage"]),
        BenchmarkTask("bad", "analysis", "Analyze", ["query_embryo_status"]),
    ]
    evaluator = CopilotBenchmarkEvaluator(tasks=tasks)

    report = evaluator.evaluate_traces(
        {
            "ok": [{"name": "move_stage", "input": {}}],
            "bad": [],
        }
    )

    assert report.num_tasks == 2
    assert report.category_scores["navigation"] == 1.0
    assert report.category_scores["analysis"] < 1.0


@pytest.mark.asyncio
async def test_mock_client_records_scripted_responses():
    client = MockQueueServerClient(stage_position=(10.0, 20.0))
    client.script_response("detect_embryos", {"success": True, "embryos": ["e1"]})

    await client.move_to_position(100.0, 200.0)
    result = await client.detect_embryos()

    assert result["embryos"] == ["e1"]
    assert client.recorded_calls("move_to_position") == [
        {"method": "move_to_position", "x": 100.0, "y": 200.0}
    ]


@pytest.mark.asyncio
async def test_mock_client_can_script_failures():
    client = MockQueueServerClient()
    client.fail("move_to_position", RuntimeError("stage limit"))

    with pytest.raises(RuntimeError, match="stage limit"):
        await client.move_to_position(999999.0, 0.0)

    assert client.recorded_calls("move_to_position")[0]["x"] == 999999.0
