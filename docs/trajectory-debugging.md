# Trajectory Debugging

Gently already captures several useful session artifacts, including
`events.jsonl`, `decisions.jsonl`, `timeline.jsonl`, perception traces, and
interaction logs. The debug exporter packages those artifacts into a compact
context bundle for a coding agent.

## Create a Bundle

```shell
python -m gently.debug --session abc12345 --annotate "should query embryo position before moving"
```

Options:

- `--root`: storage root, defaulting to `GENTLY_STORAGE_PATH` or `D:/Gently3`.
- `--output-dir`: explicit destination for the bundle.
- `--max-records`: number of transcript excerpt records to include.

The command writes:

- `debug_context.md`: prompt/context for a coding agent.
- `artifacts.json`: artifact inventory and source-file hints.
- `transcript_excerpt.jsonl`: compact tail records from event, decision,
  timeline, and interaction logs.
- `profile_summary.json`: profiler span counts, duration by component, and
  slowest spans when `profile.jsonl` or `profile_spans.jsonl` exists.
- `source_files.txt`: source files inferred from tool calls in the logs.

## Profiler Span Format

Runtime profilers can write append-only JSONL records to either `profile.jsonl`
or `profile_spans.jsonl` in the session directory. The exporter recognizes
records with these fields:

- `timestamp` or `start_time`
- `component`, `subsystem`, `agent`, or `tool_name`
- `operation`, `name`, `tool_name`, or `event`
- `duration_ms`, `elapsed_ms`, `wall_ms`, or `duration_s`
- optional `status` or `outcome`

The schema is deliberately permissive so LLM calls, tool calls, hardware queue
waits, perception steps, file I/O, and UI/WebSocket events can all be summarized
without forcing them into one runtime dependency.

## Workflow

1. Run or replay a Gently agent scenario until the behavior diverges from what was
   expected.
2. Export the debug bundle with an annotation describing the expected behavior.
3. Give the bundle to a coding agent with access to the repo.
4. Ask for a root-cause analysis, a targeted fix, and an offline regression
   test.

The exporter does not require live hardware and does not copy large image or
volume payloads into the bundle.
