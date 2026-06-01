"""Prepare trajectory-debugging context for coding agents."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "debugging_prompt.md"
_TOOL_DECORATOR_RE = re.compile(r"name\s*=\s*['\"]([^'\"]+)['\"]")


@dataclass(frozen=True)
class ArtifactSummary:
    """Small summary of a session artifact included in a debug bundle."""

    kind: str
    path: str
    exists: bool
    bytes: int = 0
    lines: int = 0


@dataclass(frozen=True)
class DebugBundle:
    """Paths and metadata for a generated debug export."""

    session_id: str
    session_dir: str
    output_dir: str
    annotation: Optional[str]
    artifacts: List[ArtifactSummary] = field(default_factory=list)
    source_files: List[str] = field(default_factory=list)
    profile_summary: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["artifacts"] = [asdict(artifact) for artifact in self.artifacts]
        data["profile_summary"] = dict(self.profile_summary)
        return data


def resolve_session_dir(session: str, root: Optional[Path] = None) -> Tuple[str, Path]:
    """Resolve a session id/prefix or direct path to a session directory."""
    direct = Path(session)
    if direct.exists() and direct.is_dir():
        return direct.name, direct

    from gently.core.file_store import FileStore

    root_path = Path(root or os.environ.get("GENTLY_STORAGE_PATH", "D:/Gently3"))
    store = FileStore(root_path)
    sessions = store.list_sessions()
    matches = [
        item for item in sessions
        if str(item.get("session_id", "")).startswith(session)
    ]
    if not matches:
        raise FileNotFoundError(f"No session matching {session!r} under {root_path}")
    if len(matches) > 1:
        ids = ", ".join(str(item.get("session_id")) for item in matches)
        raise ValueError(f"Multiple sessions match {session!r}: {ids}")

    session_id = str(matches[0]["session_id"])
    session_dir = store._session_dir(session_id)
    if session_dir is None or not session_dir.exists():
        raise FileNotFoundError(f"Session directory not found for {session_id}")
    return session_id, session_dir


def prepare_debug_context(
    session: str,
    *,
    root: Optional[Path] = None,
    output_dir: Optional[Path] = None,
    annotation: Optional[str] = None,
    max_records: int = 80,
) -> DebugBundle:
    """Create a debug bundle for a session and return its metadata."""
    session_id, session_dir = resolve_session_dir(session, root=root)
    if root is not None:
        root_path = Path(root)
    elif len(session_dir.parents) > 1:
        root_path = session_dir.parents[1]
    else:
        root_path = session_dir.parent
    if output_dir is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = session_dir / "debug_exports" / stamp
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts = collect_artifacts(session_dir, root_path=root_path, session_id=session_id)
    source_files = infer_relevant_source_files(session_dir, artifacts)
    transcript_records = collect_transcript_excerpt(artifacts, max_records=max_records)
    profile_summary = summarize_profile_records(artifacts)

    bundle = DebugBundle(
        session_id=session_id,
        session_dir=str(session_dir),
        output_dir=str(output_dir),
        annotation=annotation,
        artifacts=artifacts,
        source_files=source_files,
        profile_summary=profile_summary,
    )

    (output_dir / "artifacts.json").write_text(
        json.dumps(bundle.to_dict(), indent=2),
        encoding="utf-8",
    )
    (output_dir / "source_files.txt").write_text(
        "\n".join(source_files) + ("\n" if source_files else ""),
        encoding="utf-8",
    )
    _write_jsonl(output_dir / "transcript_excerpt.jsonl", transcript_records)
    (output_dir / "profile_summary.json").write_text(
        json.dumps(profile_summary, indent=2),
        encoding="utf-8",
    )
    (output_dir / "debug_context.md").write_text(
        build_debug_prompt(bundle, transcript_records),
        encoding="utf-8",
    )
    return bundle


def collect_artifacts(
    session_dir: Path,
    *,
    root_path: Optional[Path] = None,
    session_id: Optional[str] = None,
) -> List[ArtifactSummary]:
    """Collect known session artifacts without reading large binary payloads."""
    candidates = [
        ("session", session_dir / "session.yaml"),
        ("events", session_dir / "events.jsonl"),
        ("decisions", session_dir / "decisions.jsonl"),
        ("timeline", session_dir / "timeline.jsonl"),
        ("profile", session_dir / "profile.jsonl"),
        ("profile_spans", session_dir / "profile_spans.jsonl"),
        ("interaction_log", session_dir / "interaction_log.jsonl"),
    ]
    if root_path is not None and session_id:
        candidates.append(
            ("interaction_logger", root_path / "interaction_logs" / f"{session_id}.jsonl")
        )

    for trace in sorted(session_dir.glob("embryos/*/traces/*.json"))[:25]:
        candidates.append(("perception_trace", trace))
    for predictions in sorted(session_dir.glob("embryos/*/predictions.jsonl"))[:25]:
        candidates.append(("predictions", predictions))

    return [_summarize_artifact(kind, path) for kind, path in candidates]


def collect_transcript_excerpt(
    artifacts: Sequence[ArtifactSummary],
    *,
    max_records: int = 80,
) -> List[Dict[str, Any]]:
    """Read tail records from text/jsonl artifacts for compact debugging."""
    text_kinds = {"events", "decisions", "timeline", "interaction_log", "interaction_logger"}
    records: List[Dict[str, Any]] = []
    per_file = max(1, max_records // max(1, len([a for a in artifacts if a.kind in text_kinds])))
    for artifact in artifacts:
        if not artifact.exists or artifact.kind not in text_kinds:
            continue
        for record in _read_jsonl_tail(Path(artifact.path), per_file):
            records.append({"artifact": artifact.kind, "record": record})
    return records[-max_records:]


def summarize_profile_records(
    artifacts: Sequence[ArtifactSummary],
    *,
    max_records: int = 1000,
    max_slowest: int = 10,
) -> Dict[str, Any]:
    """Summarize profiler span logs for the debug bundle."""
    profile_kinds = {"profile", "profile_spans"}
    spans: List[Dict[str, Any]] = []
    duration_by_component: Dict[str, float] = {}

    for artifact in artifacts:
        if not artifact.exists or artifact.kind not in profile_kinds:
            continue
        for record in _read_jsonl_tail(Path(artifact.path), max_records):
            if not isinstance(record, Mapping):
                continue
            component = str(
                record.get("component")
                or record.get("subsystem")
                or record.get("agent")
                or record.get("tool_name")
                or "unknown"
            )
            operation = str(
                record.get("operation")
                or record.get("name")
                or record.get("tool_name")
                or record.get("event")
                or "unknown"
            )
            duration_ms = _duration_ms(record)
            span = {
                "artifact": artifact.kind,
                "timestamp": record.get("timestamp") or record.get("start_time"),
                "component": component,
                "operation": operation,
                "duration_ms": duration_ms,
                "status": record.get("status") or record.get("outcome"),
            }
            spans.append(span)
            if duration_ms is not None:
                duration_by_component[component] = (
                    duration_by_component.get(component, 0.0) + duration_ms
                )

    slowest = sorted(
        [span for span in spans if span["duration_ms"] is not None],
        key=lambda span: span["duration_ms"],
        reverse=True,
    )[:max_slowest]
    return {
        "span_count": len(spans),
        "duration_by_component_ms": {
            component: round(duration, 3)
            for component, duration in sorted(duration_by_component.items())
        },
        "slowest_spans": slowest,
    }


def infer_relevant_source_files(
    session_dir: Path,
    artifacts: Sequence[ArtifactSummary],
    *,
    repo_root: Optional[Path] = None,
) -> List[str]:
    """Infer relevant source files from tool names found in session logs."""
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    tool_names = extract_tool_names(artifacts)
    source_index = build_tool_source_index(repo_root)
    files: Set[str] = set()
    for name in tool_names:
        path = source_index.get(name)
        if path:
            files.add(path.relative_to(repo_root).as_posix())

    if tool_names:
        files.update(
            [
                "gently/app/agent.py",
                "gently/harness/conversation.py",
                "gently/eval/decision_log.py",
            ]
        )
    if (session_dir / "events.jsonl").exists():
        files.add("gently/eval/event_capture.py")
        files.add("gently/eval/event_replay.py")

    return sorted(files)


def extract_tool_names(artifacts: Sequence[ArtifactSummary]) -> Set[str]:
    """Extract tool names from decision and interaction logs."""
    names: Set[str] = set()
    for artifact in artifacts:
        if not artifact.exists or artifact.kind not in {
            "decisions",
            "interaction_log",
            "interaction_logger",
        }:
            continue
        for record in _read_jsonl_tail(Path(artifact.path), 200):
            names.update(_find_tool_names(record))
    return names


def build_tool_source_index(repo_root: Path) -> Dict[str, Path]:
    """Map @tool decorator names to source files."""
    index: Dict[str, Path] = {}
    tools_dir = repo_root / "gently" / "app" / "tools"
    if not tools_dir.exists():
        return index
    for path in tools_dir.glob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _TOOL_DECORATOR_RE.finditer(text):
            index.setdefault(match.group(1), path)
    return index


def build_debug_prompt(
    bundle: DebugBundle,
    transcript_records: Sequence[Mapping[str, Any]],
) -> str:
    """Build the markdown context handed to a coding agent."""
    template = PROMPT_TEMPLATE.read_text(encoding="utf-8")
    artifact_lines = [
        f"- {artifact.kind}: `{artifact.path}` ({artifact.lines} lines, {artifact.bytes} bytes)"
        for artifact in bundle.artifacts
        if artifact.exists
    ]
    missing_lines = [
        f"- {artifact.kind}: `{artifact.path}`"
        for artifact in bundle.artifacts
        if not artifact.exists
    ]
    source_lines = [f"- `{path}`" for path in bundle.source_files]

    return "\n".join(
        [
            template,
            "",
            "## Session",
            "",
            f"- Session id: `{bundle.session_id}`",
            f"- Session directory: `{bundle.session_dir}`",
            f"- Annotation: {bundle.annotation or '(none supplied)'}",
            "",
            "## Included Artifacts",
            "",
            *(artifact_lines or ["- (none found)"]),
            "",
            "## Missing Expected Artifacts",
            "",
            *(missing_lines or ["- (none)"]),
            "",
            "## Relevant Source Files",
            "",
            *(source_lines or ["- (no tool-specific source files inferred)"]),
            "",
            "## Transcript Excerpt",
            "",
            f"`transcript_excerpt.jsonl` contains {len(transcript_records)} compact records.",
            "",
            "## Profile Summary",
            "",
            _format_profile_summary(bundle.profile_summary),
            "",
            "## Suggested Debugging Output",
            "",
            "1. Root cause.",
            "2. Smallest code or prompt fix.",
            "3. Offline regression test.",
            "4. Any live-hardware validation that remains necessary.",
            "",
        ]
    )


def _summarize_artifact(kind: str, path: Path) -> ArtifactSummary:
    if not path.exists():
        return ArtifactSummary(kind=kind, path=str(path), exists=False)
    stat = path.stat()
    lines = 0
    if path.suffix.lower() in {".jsonl", ".yaml", ".yml", ".json", ".md", ".txt"}:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                lines = sum(1 for _ in f)
        except OSError:
            lines = 0
    return ArtifactSummary(
        kind=kind,
        path=str(path),
        exists=True,
        bytes=stat.st_size,
        lines=lines,
    )


def _read_jsonl_tail(path: Path, max_lines: int) -> List[Any]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    out: List[Any] = []
    for raw in lines[-max_lines:]:
        if not raw.strip():
            continue
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            out.append({"raw": raw})
    return out


def _find_tool_names(value: Any) -> Set[str]:
    names: Set[str] = set()
    if isinstance(value, Mapping):
        if isinstance(value.get("tool_name"), str):
            names.add(value["tool_name"])
        if isinstance(value.get("name"), str) and (
            "input" in value or "arguments" in value or "params" in value
        ):
            names.add(value["name"])
        for nested in value.values():
            names.update(_find_tool_names(nested))
    elif isinstance(value, list):
        for item in value:
            names.update(_find_tool_names(item))
    return names


def _duration_ms(record: Mapping[str, Any]) -> Optional[float]:
    for key in ("duration_ms", "elapsed_ms", "wall_ms"):
        if key in record and record[key] is not None:
            try:
                return round(float(record[key]), 3)
            except (TypeError, ValueError):
                return None
    if "duration_s" in record and record["duration_s"] is not None:
        try:
            return round(float(record["duration_s"]) * 1000.0, 3)
        except (TypeError, ValueError):
            return None
    return None


def _format_profile_summary(summary: Mapping[str, Any]) -> str:
    if not summary or not summary.get("span_count"):
        return "No profiler spans were found."

    lines = [f"Profiler spans: {summary.get('span_count')}"]
    durations = summary.get("duration_by_component_ms") or {}
    if durations:
        lines.append("")
        lines.append("Duration by component:")
        for component, duration in durations.items():
            lines.append(f"- {component}: {duration} ms")

    slowest = summary.get("slowest_spans") or []
    if slowest:
        lines.append("")
        lines.append("Slowest spans:")
        for span in slowest[:5]:
            lines.append(
                f"- {span.get('component')}.{span.get('operation')}: "
                f"{span.get('duration_ms')} ms"
            )
    return "\n".join(lines)


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, default=str) + "\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a trajectory-debugging context bundle for a Gently session."
    )
    parser.add_argument("--session", required=True, help="Session id/prefix or session directory")
    parser.add_argument("--root", default=None, help="Gently storage root")
    parser.add_argument("--output-dir", default=None, help="Debug bundle output directory")
    parser.add_argument("--annotate", default=None, help="Expected behavior or failure note")
    parser.add_argument("--max-records", type=int, default=80, help="Transcript records to include")
    args = parser.parse_args(argv)

    bundle = prepare_debug_context(
        args.session,
        root=Path(args.root) if args.root else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        annotation=args.annotate,
        max_records=args.max_records,
    )
    print(bundle.output_dir)
    return 0
