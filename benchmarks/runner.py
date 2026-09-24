"""
Benchmark Runner

CLI for running benchmarks against the agent.

Usage:
    python -m benchmarks.runner agent --tags timelapse
    python -m benchmarks.runner compare before.json after.json
"""

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def run_agent_benchmark(args):
    """Run agent tool-calling benchmark"""
    from .agent.evaluator import AgentEvaluator

    # Parse tags
    tags = args.tags.split(",") if args.tags else None

    # Initialize evaluator
    evaluator = AgentEvaluator()

    # TODO: Initialize agent
    # For now, show what would be tested
    logger.info("=" * 60)
    logger.info("AGENT BENCHMARK")
    logger.info("=" * 60)

    cases = evaluator.test_cases
    if tags:
        cases = [c for c in cases if any(t in c.get("tags", []) for t in tags)]

    logger.info(f"\nTest cases to run: {len(cases)}")
    if tags:
        logger.info(f"Filtered by tags: {tags}")

    logger.info("\nTest cases:")
    for case in cases:
        logger.info(f"  [{case['id']}] {case['query'][:50]}...")
        logger.info(f"      Expected: {case['expected_tool']}")

    logger.info("\n" + "=" * 60)
    logger.info("NOTE: Actual benchmark execution requires agent integration.")
    logger.info("Add --run flag once agent.get_tool_call() is implemented.")
    logger.info("=" * 60)

    if args.run:
        # TODO: Actually run the benchmark
        # agent = MicroscopyAgent(...)
        # report = await evaluator.run_benchmark(agent, tags=tags)
        logger.error("Agent dry-run mode not yet implemented")
        return 1

    return 0


def run_workflow_benchmark(args):
    """Score agent workflow traces against the standard task suite."""
    from .evaluator import AgentWorkflowBenchmarkEvaluator, load_tasks

    tags = args.tags.split(",") if args.tags else None
    tasks = load_tasks(tags=tags)
    evaluator = AgentWorkflowBenchmarkEvaluator(tasks=tasks)

    if not args.trace:
        logger.info("=" * 60)
        logger.info("AGENT WORKFLOW BENCHMARK TASKS")
        logger.info("=" * 60)
        for task in tasks:
            logger.info("[%s] %s", task.id, task.prompt)
            logger.info("    category=%s expected=%s", task.category, task.expected_tools)
            checklist_items = sum(
                len(items)
                for items in [
                    task.safety_constraints,
                    task.scientific_validity,
                    task.trace_quality_checks,
                    task.operator_experience_checks,
                    task.expected_evidence,
                ]
            )
            if checklist_items:
                logger.info("    manual review checks=%d", checklist_items)
        logger.info("")
        logger.info("Pass --trace path/to/traces.json to score a run.")
        return 0

    with open(args.trace, encoding="utf-8") as f:
        trace_data = json.load(f)
    traces = trace_data.get("traces", trace_data)

    report = evaluator.evaluate_traces(traces)
    payload = report.to_dict()

    logger.info("=" * 60)
    logger.info("AGENT WORKFLOW BENCHMARK")
    logger.info("=" * 60)
    logger.info("Tasks: %d", report.num_tasks)
    logger.info("Pass rate: %.1f%%", payload["summary"]["pass_rate"] * 100)
    logger.info("Average score: %.1f%%", report.average_score * 100)
    logger.info("Manual review tasks: %d", payload["summary"]["manual_review_tasks"])
    for category, score in report.category_scores.items():
        logger.info("  %s: %.1f%%", category, score * 100)

    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.info("Wrote report: %s", output)

    return 0


def compare_reports(args):
    """Compare two benchmark reports"""

    with open(args.before) as f:
        before_data = json.load(f)

    with open(args.after) as f:
        after_data = json.load(f)

    # Reconstruct reports (simplified)
    logger.info("=" * 60)
    logger.info("BENCHMARK COMPARISON")
    logger.info("=" * 60)

    logger.info(f"\nBefore: {args.before}")
    logger.info(f"After:  {args.after}")

    # Show deltas
    before_summary = before_data.get("summary", {})
    after_summary = after_data.get("summary", {})

    metrics = [
        ("Tool Accuracy", "tool_accuracy", "{:.1%}"),
        ("Param Accuracy", "param_accuracy", "{:.1%}"),
        ("Pass Rate", "pass_rate", "{:.1%}"),
    ]

    logger.info("\nMetrics:")
    for name, key, fmt in metrics:
        before_val = before_summary.get(key, 0)
        after_val = after_summary.get(key, 0)
        delta = after_val - before_val

        delta_str = f"+{fmt.format(delta)}" if delta > 0 else fmt.format(delta)
        status = "improved" if delta > 0 else ("regressed" if delta < 0 else "unchanged")

        logger.info(
            f"  {name}: {fmt.format(before_val)} -> {fmt.format(after_val)}"
            f" ({delta_str}) [{status}]"
        )

    # Token comparison
    before_tokens = before_data.get("tokens", {})
    after_tokens = after_data.get("tokens", {})

    before_total = before_tokens.get("total_input", 0) + before_tokens.get("total_output", 0)
    after_total = after_tokens.get("total_input", 0) + after_tokens.get("total_output", 0)
    token_delta = after_total - before_total

    logger.info("\nTokens:")
    logger.info(f"  Total: {before_total:,} -> {after_total:,} ({token_delta:+,})")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Gently Benchmark Runner")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Agent benchmark
    agent_parser = subparsers.add_parser("agent", help="Run agent benchmarks")
    agent_parser.add_argument("--tags", help="Comma-separated tags to filter")
    agent_parser.add_argument("--run", action="store_true", help="Actually run (vs dry-run)")
    agent_parser.add_argument("--output", help="Output file for results")

    # Agent workflow benchmark
    workflow_parser = subparsers.add_parser(
        "workflow",
        help="List or score deterministic agent workflow benchmarks",
    )
    workflow_parser.add_argument("--tags", help="Comma-separated tags to filter")
    workflow_parser.add_argument("--trace", help="JSON mapping task ids to tool-call traces")
    workflow_parser.add_argument("--output", help="Output file for scored report")

    legacy_parser = subparsers.add_parser(
        "copilot",
        help=argparse.SUPPRESS,
    )
    legacy_parser.add_argument("--tags", help=argparse.SUPPRESS)
    legacy_parser.add_argument("--trace", help=argparse.SUPPRESS)
    legacy_parser.add_argument("--output", help=argparse.SUPPRESS)

    # Compare reports
    compare_parser = subparsers.add_parser("compare", help="Compare two reports")
    compare_parser.add_argument("before", help="Before report JSON")
    compare_parser.add_argument("after", help="After report JSON")

    args = parser.parse_args()

    if args.command == "agent":
        return asyncio.run(run_agent_benchmark(args))
    elif args.command in {"workflow", "copilot"}:
        return run_workflow_benchmark(args)
    elif args.command == "compare":
        return compare_reports(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
