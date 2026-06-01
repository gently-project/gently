"""Deterministic agent workflow benchmark task scoring.

This module scores recorded/planned tool traces against benchmark task
definitions. It does not call an LLM; callers can feed traces from a dry-run
agent, a replay harness, or hand-authored regression cases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


DEFAULT_TASKS_PATH = Path(__file__).parent / "tasks" / "agent_workflows.json"


@dataclass(frozen=True)
class BenchmarkTask:
    """One expected Gently agent workflow."""

    id: str
    category: str
    prompt: str
    expected_tools: List[str]
    expected_params: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    expected_recovery_tools: List[str] = field(default_factory=list)
    failure_scenario: Optional[str] = None
    safety_constraints: List[str] = field(default_factory=list)
    scientific_validity: List[str] = field(default_factory=list)
    trace_quality_checks: List[str] = field(default_factory=list)
    operator_experience_checks: List[str] = field(default_factory=list)
    expected_evidence: List[str] = field(default_factory=list)
    max_tool_calls: Optional[int] = None
    tags: List[str] = field(default_factory=list)
    weight: float = 1.0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BenchmarkTask":
        return cls(
            id=str(data["id"]),
            category=str(data["category"]),
            prompt=str(data["prompt"]),
            expected_tools=list(data.get("expected_tools") or []),
            expected_params=data.get("expected_params") or {},
            expected_recovery_tools=list(data.get("expected_recovery_tools") or []),
            failure_scenario=data.get("failure_scenario"),
            safety_constraints=list(data.get("safety_constraints") or []),
            scientific_validity=list(data.get("scientific_validity") or []),
            trace_quality_checks=list(data.get("trace_quality_checks") or []),
            operator_experience_checks=list(data.get("operator_experience_checks") or []),
            expected_evidence=list(data.get("expected_evidence") or []),
            max_tool_calls=data.get("max_tool_calls"),
            tags=list(data.get("tags") or []),
            weight=float(data.get("weight", 1.0)),
        )


@dataclass(frozen=True)
class BenchmarkResult:
    """Score for one benchmark task."""

    task_id: str
    category: str
    prompt: str
    expected_tools: List[str]
    actual_tools: List[str]
    completion_score: float
    parameter_score: float
    efficiency_score: float
    error_handling_score: float
    total_score: float
    errors: List[str] = field(default_factory=list)
    review_checklist: Mapping[str, List[str]] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.total_score >= 0.85 and not self.errors

    @property
    def manual_review_required(self) -> bool:
        return any(self.review_checklist.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "category": self.category,
            "prompt": self.prompt,
            "expected_tools": self.expected_tools,
            "actual_tools": self.actual_tools,
            "scores": {
                "completion": self.completion_score,
                "parameters": self.parameter_score,
                "efficiency": self.efficiency_score,
                "error_handling": self.error_handling_score,
                "total": self.total_score,
            },
            "passed": self.passed,
            "errors": self.errors,
            "manual_review_required": self.manual_review_required,
            "review_checklist": {
                name: list(checks)
                for name, checks in self.review_checklist.items()
                if checks
            },
        }


@dataclass(frozen=True)
class BenchmarkReport:
    """Aggregate benchmark run summary."""

    timestamp: str
    num_tasks: int
    num_passed: int
    average_score: float
    category_scores: Mapping[str, float]
    results: List[BenchmarkResult]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "summary": {
                "num_tasks": self.num_tasks,
                "num_passed": self.num_passed,
                "pass_rate": self.num_passed / self.num_tasks if self.num_tasks else 0.0,
                "average_score": self.average_score,
                "category_scores": dict(self.category_scores),
                "manual_review_tasks": sum(
                    1 for result in self.results if result.manual_review_required
                ),
            },
            "metadata": dict(self.metadata),
            "results": [result.to_dict() for result in self.results],
        }


def load_tasks(path: Path = DEFAULT_TASKS_PATH, tags: Optional[Iterable[str]] = None) -> List[BenchmarkTask]:
    """Load benchmark tasks from a JSON task suite."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    tasks = [BenchmarkTask.from_dict(item) for item in data.get("tasks", [])]
    if tags is None:
        return tasks

    wanted = set(tags)
    return [task for task in tasks if wanted.intersection(task.tags)]


def _tool_name(call: Mapping[str, Any]) -> Optional[str]:
    return call.get("name") or call.get("tool") or call.get("tool_name")


def _tool_input(call: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = call.get("input")
    if payload is None:
        payload = call.get("params")
    if payload is None:
        payload = call.get("arguments")
    return payload or {}


def _ordered_match_score(expected: Sequence[str], actual: Sequence[str]) -> float:
    if not expected:
        return 1.0

    cursor = 0
    matched = 0
    for expected_name in expected:
        for index in range(cursor, len(actual)):
            if actual[index] == expected_name:
                matched += 1
                cursor = index + 1
                break
    return matched / len(expected)


def _review_checklist(task: BenchmarkTask) -> Dict[str, List[str]]:
    return {
        "safety_constraints": list(task.safety_constraints),
        "scientific_validity": list(task.scientific_validity),
        "trace_quality": list(task.trace_quality_checks),
        "operator_experience": list(task.operator_experience_checks),
        "expected_evidence": list(task.expected_evidence),
    }


class AgentWorkflowBenchmarkEvaluator:
    """Score Gently agent tool traces against workflow benchmark tasks."""

    def __init__(self, tasks: Optional[Sequence[BenchmarkTask]] = None):
        self.tasks = list(tasks) if tasks is not None else load_tasks()

    def evaluate_task(
        self,
        task: BenchmarkTask,
        tool_calls: Sequence[Mapping[str, Any]],
        *,
        error: Optional[str] = None,
    ) -> BenchmarkResult:
        actual_tools = [name for name in (_tool_name(call) for call in tool_calls) if name]
        errors: List[str] = []

        completion_score = _ordered_match_score(task.expected_tools, actual_tools)
        if completion_score < 1.0:
            missing = [name for name in task.expected_tools if name not in actual_tools]
            errors.extend(f"missing expected tool: {name}" for name in missing)

        parameter_score = self._parameter_score(task, tool_calls, errors)
        efficiency_score = self._efficiency_score(task, actual_tools)
        error_handling_score = self._error_handling_score(task, actual_tools, error)
        if error:
            errors.append(error)

        total_score = (
            0.45 * completion_score
            + 0.25 * parameter_score
            + 0.15 * efficiency_score
            + 0.15 * error_handling_score
        )

        return BenchmarkResult(
            task_id=task.id,
            category=task.category,
            prompt=task.prompt,
            expected_tools=task.expected_tools,
            actual_tools=actual_tools,
            completion_score=round(completion_score, 4),
            parameter_score=round(parameter_score, 4),
            efficiency_score=round(efficiency_score, 4),
            error_handling_score=round(error_handling_score, 4),
            total_score=round(total_score, 4),
            errors=errors,
            review_checklist=_review_checklist(task),
        )

    def evaluate_traces(
        self,
        traces_by_task_id: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        errors_by_task_id: Optional[Mapping[str, str]] = None,
    ) -> BenchmarkReport:
        errors_by_task_id = errors_by_task_id or {}
        results = [
            self.evaluate_task(
                task,
                traces_by_task_id.get(task.id, []),
                error=errors_by_task_id.get(task.id),
            )
            for task in self.tasks
        ]
        return self._report(results)

    def _parameter_score(
        self,
        task: BenchmarkTask,
        tool_calls: Sequence[Mapping[str, Any]],
        errors: List[str],
    ) -> float:
        if not task.expected_params:
            return 1.0

        checks = 0
        passed = 0
        calls_by_name: Dict[str, List[Mapping[str, Any]]] = {}
        for call in tool_calls:
            name = _tool_name(call)
            if name:
                calls_by_name.setdefault(name, []).append(call)

        for tool_name, expected_params in task.expected_params.items():
            calls = calls_by_name.get(tool_name) or []
            if not calls:
                checks += len(expected_params)
                errors.append(f"missing params because tool was not called: {tool_name}")
                continue
            actual_params = _tool_input(calls[0])
            for key, expected_value in expected_params.items():
                checks += 1
                if actual_params.get(key) == expected_value:
                    passed += 1
                else:
                    errors.append(
                        f"{tool_name}.{key}: expected {expected_value!r}, "
                        f"got {actual_params.get(key)!r}"
                    )

        return passed / checks if checks else 1.0

    def _efficiency_score(self, task: BenchmarkTask, actual_tools: Sequence[str]) -> float:
        if not actual_tools:
            return 1.0 if not task.expected_tools else 0.0
        if task.max_tool_calls is not None and len(actual_tools) > task.max_tool_calls:
            return task.max_tool_calls / len(actual_tools)
        optimal = max(len(task.expected_tools), 1)
        return min(1.0, optimal / len(actual_tools))

    def _error_handling_score(
        self,
        task: BenchmarkTask,
        actual_tools: Sequence[str],
        error: Optional[str],
    ) -> float:
        if not task.failure_scenario:
            return 0.0 if error else 1.0
        if error:
            return 0.0
        if not task.expected_recovery_tools:
            return 1.0
        return _ordered_match_score(task.expected_recovery_tools, actual_tools)

    def _report(self, results: Sequence[BenchmarkResult]) -> BenchmarkReport:
        category_totals: Dict[str, List[float]] = {}
        for result in results:
            category_totals.setdefault(result.category, []).append(result.total_score)

        category_scores = {
            category: round(sum(scores) / len(scores), 4)
            for category, scores in category_totals.items()
        }
        average = sum(result.total_score for result in results) / len(results) if results else 0.0
        return BenchmarkReport(
            timestamp=datetime.now().isoformat(),
            num_tasks=len(results),
            num_passed=sum(1 for result in results if result.passed),
            average_score=round(average, 4),
            category_scores=category_scores,
            results=list(results),
            metadata={"task_count": len(self.tasks)},
        )


# Backward-compatible alias for older callers while the benchmark terminology
# moves away from "copilot".
CopilotBenchmarkEvaluator = AgentWorkflowBenchmarkEvaluator
