"""
Gently Benchmarks

Evaluation framework for measuring agent and CV subagent performance.
"""

from .evaluator import (
    AgentWorkflowBenchmarkEvaluator,
    BenchmarkTask,
    CopilotBenchmarkEvaluator,
    load_tasks,
)

__version__ = "0.9.2"  # Keep in sync with gently/__init__.py __version__

__all__ = [
    "BenchmarkTask",
    "AgentWorkflowBenchmarkEvaluator",
    "CopilotBenchmarkEvaluator",
    "load_tasks",
]
