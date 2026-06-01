"""Offline replay benchmark for structured plan generation.

This benchmark exercises the `create_structured_plan` tool against a fresh
ContextStore. It is intentionally deterministic: no LLM, browser session, or
microscope connection is required.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional

from gently.harness.memory.store import ContextStore
from gently.harness.tools.registry import get_tool_registry

# Import registers the plan-mode tools with the global registry.
from gently.harness.plan_mode.tools import planning  # noqa: F401


DEFAULT_PLAN_PAYLOAD: Dict[str, Any] = {
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
}


def _count_plan_records(store: ContextStore, campaign_id: str) -> Dict[str, int]:
    phases = store.get_subcampaigns(campaign_id)
    campaign_ids = [campaign_id] + [phase.id for phase in phases]

    items = []
    dependency_count = 0
    for cid in campaign_ids:
        campaign_items = store.get_plan_items(campaign_id=cid)
        items.extend(campaign_items)
        for item in campaign_items:
            dependency_count += len(store.get_plan_item_dependencies(item.id))

    return {
        "campaigns": 1,
        "phases": len(phases),
        "items": len(items),
        "dependencies": dependency_count,
    }


def _expected_dependency_count(items: list[Mapping[str, Any]]) -> int:
    count = 0
    for item in items:
        raw = item.get("depends_on") or []
        count += 1 if isinstance(raw, str) else len(raw)
    return count


async def run_structured_plan_replay(
    workdir: Path,
    payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the deterministic structured-plan replay and return a JSON report."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    plan_payload = dict(payload or DEFAULT_PLAN_PAYLOAD)

    store = ContextStore(workdir / "structured_plan_replay.db")
    agent = SimpleNamespace(context_store=store)
    started = time.perf_counter()
    try:
        result = await get_tool_registry().execute(
            "create_structured_plan",
            plan_payload,
            {"agent": agent},
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

        campaign = store.resolve_campaign(str(plan_payload["shorthand"]))
        counts = (
            _count_plan_records(store, campaign.id)
            if campaign is not None
            else {"campaigns": 0, "phases": 0, "items": 0, "dependencies": 0}
        )
        expected_counts = {
            "campaigns": 1,
            "phases": len(plan_payload.get("phases") or []),
            "items": len(plan_payload.get("items") or []),
            "dependencies": _expected_dependency_count(plan_payload.get("items") or []),
        }
        passed = (
            campaign is not None
            and not str(result).startswith("Error:")
            and counts == expected_counts
        )

        return {
            "benchmark": "structured_plan_replay",
            "passed": passed,
            "elapsed_ms": elapsed_ms,
            "tool_calls": [
                {
                    "name": "create_structured_plan",
                    "phases": expected_counts["phases"],
                    "items": expected_counts["items"],
                    "dependencies": expected_counts["dependencies"],
                }
            ],
            "expected_counts": expected_counts,
            "actual_counts": counts,
            "campaign_id": campaign.id if campaign else None,
            "tool_result_excerpt": str(result).splitlines()[:8],
        }
    finally:
        store.close()


async def _run_cli(args: argparse.Namespace) -> int:
    if args.workdir:
        report = await run_structured_plan_replay(Path(args.workdir))
    else:
        with tempfile.TemporaryDirectory(prefix="gently-structured-plan-") as tmp:
            report = await run_structured_plan_replay(Path(tmp))

    payload = json.dumps(report, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    print(payload)
    return 0 if report["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the structured plan replay benchmark")
    parser.add_argument("--workdir", help="Directory for the temporary ContextStore database")
    parser.add_argument("--output", help="Optional JSON report path")
    return asyncio.run(_run_cli(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
