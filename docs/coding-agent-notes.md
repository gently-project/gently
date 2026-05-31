# Coding-Agent Notes

The copilot can leave durable notes for a future coding-agent pass with the
`leave_coding_agent_note` tool. Notes are append-only JSONL records intended for
bug reports, internal errors, implementation feedback, or user requests that
should be addressed in code.

When a FileStore session is active, notes are written to:

```text
<session_dir>/coding_agent_notes.jsonl
```

If no session directory can be resolved, the fallback path is:

```text
<agent.storage_path>/coding_agent_notes.jsonl
```

Each record includes:

- `note_id`
- `timestamp`
- `session_id`
- `category`
- `severity`
- `message`
- optional structured `context`

The companion `list_coding_agent_notes` tool lists recent notes so the operator
or copilot can confirm what has been captured.

Example record:

```json
{
  "note_id": "8b4f0bc9e0a1",
  "timestamp": "2026-05-30T12:00:00",
  "message": "User expected movement to verify embryo position first.",
  "session_id": "abc12345",
  "category": "bug",
  "severity": "warning",
  "source": "copilot",
  "context": {"summary": "move_to_embryo skipped position lookup"}
}
```
