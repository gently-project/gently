# Copilot Benchmarks

The copilot benchmark seed defines standard microscopy workflow tasks and
scores recorded tool-call traces without requiring live hardware or an LLM call.

Task definitions live in `benchmarks/tasks/copilot_workflows.json`. Each task
declares:

- `category`: navigation, acquisition, analysis, multi_step, or error_recovery.
- `prompt`: the user request being evaluated.
- `expected_tools`: the ordered tool sequence the copilot should choose.
- `expected_params`: exact parameter checks for important tool calls.
- `max_tool_calls`: an efficiency budget.
- `failure_scenario` and `expected_recovery_tools` for recovery benchmarks.

## Scoring

`benchmarks.evaluator.CopilotBenchmarkEvaluator` computes four component
scores:

- completion: expected tools were called in order.
- parameters: expected tool parameters matched.
- efficiency: tool-call count stayed within the task budget.
- error handling: recovery tasks used expected recovery tools and completed.

The aggregate score is weighted toward task completion while still surfacing
parameter, efficiency, and recovery regressions.

## Example

```python
from benchmarks.evaluator import CopilotBenchmarkEvaluator

traces = {
    "acquisition_volume_single_embryo": [
        {"name": "acquire_volume", "input": {"embryo_id": "embryo_1"}},
    ],
}

report = CopilotBenchmarkEvaluator().evaluate_traces(traces)
print(report.to_dict()["summary"])
```

The evaluator is intentionally trace-based. A future runner can collect those
traces from a dry-run copilot, replay harness, or live session transcript, then
feed them through the same scoring code.

## Mock Hardware

Use `benchmarks.mock_client.MockQueueServerClient` when a benchmark needs
deterministic device responses:

```python
client = MockQueueServerClient(stage_position=(10.0, 20.0))
client.script_response("detect_embryos", {"success": True, "embryos": []})
```

The mock records all method calls so benchmark traces can be compared with the
expected tool sequence.
