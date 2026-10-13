# Agent Workflow Benchmarks

The benchmark concept comes before the runner: Gently should be measured on
whether it can turn a scientist's intent into a safe, inspectable, and useful
experimental trace. A scripted workflow that merely calls the expected tools is
not enough if the trace is unsafe, scientifically thin, or impossible for a
human operator to understand.

## Measurement Contract

Each benchmark task should state:

- the scientific intent being tested
- the microscope or bench context needed to satisfy that intent
- the sample state assumptions and failure modes
- the safety constraints that must never be violated
- the expected operator-facing evidence at the end of the run
- the allowed tool-call or latency budget

Scores should cover these dimensions:

- task completion: the requested experimental state was reached
- scientific validity: controls, constraints, and decision points are present
- hardware safety: unsafe motion, illumination, and device states are avoided
- trace quality: a human can reconstruct what happened and why
- efficiency: the agent avoided unnecessary tool calls and retries
- robustness: missing data, failed tools, and stale state were handled
- operator experience: the workflow needed few unnecessary clarifications
- generalization: the same concept works across imaging, bench, genetics, and
  analysis tasks

## Seed Task Suite

Task definitions live in `benchmarks/tasks/agent_workflows.json`. Each task
declares:

- `category`: navigation, acquisition, analysis, multi_step, or error_recovery.
- `prompt`: the user request being evaluated.
- `expected_tools`: the ordered tool sequence the Gently agent should choose.
- `expected_params`: exact parameter checks for important tool calls.
- `max_tool_calls`: an efficiency budget.
- `failure_scenario` and `expected_recovery_tools` for recovery benchmarks.
- `safety_constraints`: hardware or sample-safety requirements that must be
  checked by a reviewer.
- `scientific_validity`: checks for whether the run makes scientific sense.
- `trace_quality_checks`: evidence needed to reconstruct what happened and why.
- `operator_experience_checks`: checks that the operator can understand or act
  on the result.
- `expected_evidence`: artifacts or metadata that should exist after the run.

## Scoring

`benchmarks.evaluator.AgentWorkflowBenchmarkEvaluator` computes four initial
component scores:

- completion: expected tools were called in order.
- parameters: expected tool parameters matched.
- efficiency: tool-call count stayed within the task budget.
- error handling: recovery tasks used expected recovery tools and completed.

These are a first trace-based subset of the measurement contract above. They
are useful for deterministic regressions, but should not be treated as a full
quality benchmark until safety, scientific validity, trace quality, and
operator experience have corresponding evaluators.

Until those evaluators exist, each scored result also carries a
`review_checklist` and `manual_review_required` flag. A trace can pass the
deterministic score while still requiring human review of the listed safety,
scientific, trace-quality, operator-experience, and evidence checks.

## Example

```python
from benchmarks.evaluator import AgentWorkflowBenchmarkEvaluator

traces = {
    "acquisition_volume_single_embryo": [
        {"name": "acquire_volume", "input": {"embryo_id": "embryo_1"}},
    ],
}

report = AgentWorkflowBenchmarkEvaluator().evaluate_traces(traces)
print(report.to_dict()["summary"])
```

The evaluator is intentionally trace-based. A future runner can collect those
traces from a dry-run Gently agent, replay harness, or live session transcript,
then feed them through the same scoring code.

## Mock Hardware

Use `benchmarks.mock_client.MockQueueServerClient` when a benchmark needs
deterministic device responses:

```python
client = MockQueueServerClient(stage_position=(10.0, 20.0))
client.script_response("detect_embryos", {"success": True, "embryos": []})
```

The mock records all method calls so benchmark traces can be compared with the
expected tool sequence.
