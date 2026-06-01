"""Audit a Gently3 FileStore root for data inventory and obvious gaps."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml


@dataclass
class SessionAudit:
    """Audit summary for one session directory."""

    session_dir: str
    session_id: Optional[str]
    artifact_counts: Dict[str, int] = field(default_factory=dict)
    gaps: List[str] = field(default_factory=list)


@dataclass
class DatastoreAudit:
    """Top-level datastore audit report."""

    root: str
    session_count: int
    artifact_counts: Dict[str, int]
    gaps: List[str]
    sessions: List[SessionAudit]

    def to_dict(self) -> Dict:
        return asdict(self)


_COUNT_PATTERNS = {
    "session_metadata": ["session.yaml"],
    "timeline_logs": ["timeline.jsonl", "events.jsonl"],
    "interaction_logs": ["interaction_log.jsonl"],
    "snapshots": ["snapshots/*.tif"],
    "snapshot_metadata": ["snapshots/*.meta.yaml"],
    "sample_records": ["embryos/*/embryo.yaml"],
    "volumes": ["embryos/*/volumes/*.tif"],
    "volume_metadata": ["embryos/*/volumes/*.meta.yaml"],
    "projections": ["embryos/*/projections/*"],
    "perception_predictions": ["embryos/*/predictions.jsonl"],
    "perception_traces": ["embryos/*/traces/*.json"],
    "debug_exports": ["debug_exports/**/debug_context.md"],
    "profile_spans": ["profile.jsonl", "profile_spans.jsonl"],
}


def audit_datastore(root: Path) -> DatastoreAudit:
    """Scan a FileStore root and return a structured audit report."""
    root = Path(root)
    sessions_root = root / "sessions"
    sessions: List[SessionAudit] = []
    gaps: List[str] = []
    totals: Dict[str, int] = {key: 0 for key in _COUNT_PATTERNS}
    totals.update({"campaign_plans": 0, "plan_history": 0, "incoming_files": 0, "logs": 0})

    if not sessions_root.exists():
        gaps.append(f"missing sessions directory: {sessions_root}")
    else:
        for session_dir in sorted(p for p in sessions_root.iterdir() if p.is_dir()):
            session = _audit_session(session_dir)
            sessions.append(session)
            for key, count in session.artifact_counts.items():
                totals[key] = totals.get(key, 0) + count
            gaps.extend(f"{Path(session.session_dir).name}: {gap}" for gap in session.gaps)

    totals["campaign_plans"] = _count(root / "agent" / "campaigns", "**/plan/current.yaml")
    totals["plan_history"] = _count(root / "agent" / "campaigns", "**/plan/history/*.yaml")
    totals["incoming_files"] = _count(root / "incoming", "*")
    totals["logs"] = _count(root / "logs", "*")

    return DatastoreAudit(
        root=str(root),
        session_count=len(sessions),
        artifact_counts=totals,
        gaps=gaps,
        sessions=sessions,
    )


def format_audit_markdown(report: DatastoreAudit) -> str:
    """Render an audit report as concise Markdown."""
    lines = [
        f"# Datastore Audit: `{report.root}`",
        "",
        f"Sessions: {report.session_count}",
        "",
        "## Artifact Counts",
        "",
    ]
    for key, count in sorted(report.artifact_counts.items()):
        lines.append(f"- {key}: {count}")

    lines.extend(["", "## Gaps", ""])
    lines.extend(f"- {gap}" for gap in report.gaps) if report.gaps else lines.append("- none")

    lines.extend(["", "## Sessions", ""])
    for session in report.sessions:
        label = session.session_id or Path(session.session_dir).name
        lines.append(f"- `{label}`: {sum(session.artifact_counts.values())} counted artifacts")
    return "\n".join(lines) + "\n"


def _audit_session(session_dir: Path) -> SessionAudit:
    counts = {
        key: sum(_count(session_dir, pattern) for pattern in patterns)
        for key, patterns in _COUNT_PATTERNS.items()
    }
    gaps: List[str] = []
    session_data = _read_yaml(session_dir / "session.yaml", gaps)
    session_id = str(session_data.get("session_id")) if session_data else None

    if not session_data:
        gaps.append("missing or unreadable session.yaml")

    for volume in session_dir.glob("embryos/*/volumes/*.tif"):
        meta = volume.with_suffix(".meta.yaml")
        if not meta.exists():
            gaps.append(f"volume missing metadata sidecar: {volume.relative_to(session_dir)}")

    for snapshot in session_dir.glob("snapshots/*.tif"):
        meta = snapshot.with_suffix(".meta.yaml")
        if not meta.exists():
            gaps.append(f"snapshot missing metadata sidecar: {snapshot.relative_to(session_dir)}")

    for embryo in session_dir.glob("embryos/*"):
        if embryo.is_dir() and not (embryo / "embryo.yaml").exists():
            gaps.append(f"sample missing embryo.yaml: {embryo.relative_to(session_dir)}")

    return SessionAudit(
        session_dir=str(session_dir),
        session_id=session_id,
        artifact_counts=counts,
        gaps=gaps,
    )


def _count(root: Path, pattern: str) -> int:
    if not root.exists():
        return 0
    return sum(1 for p in root.glob(pattern) if p.is_file())


def _read_yaml(path: Path, gaps: List[str]) -> Dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        gaps.append(f"unreadable YAML {path.name}: {exc}")
        return {}
    return data if isinstance(data, dict) else {}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit a Gently3 datastore root")
    parser.add_argument("root", type=Path, help="Gently3/FileStore root")
    parser.add_argument("--json", action="store_true", help="Write JSON instead of Markdown")
    parser.add_argument("--output", type=Path, help="Optional report output path")
    args = parser.parse_args(argv)

    report = audit_datastore(args.root)
    text = (
        json.dumps(report.to_dict(), indent=2)
        if args.json
        else format_audit_markdown(report)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="" if text.endswith("\n") else "\n")
    return 1 if report.gaps else 0


if __name__ == "__main__":
    raise SystemExit(main())
