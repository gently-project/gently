# Datastore Audit

The FileStore safety work is a prerequisite for a larger question: whether the
current Gently3 datastore is sound enough to evolve, or whether a Gently4 store
API is needed. Do the audit before choosing a migration.

## Audit Questions

For every data product Gently creates or consumes, answer:

- Is this durable source data, derived/recomputable data, runtime state, or UI
  cache?
- Where is it stored on disk?
- Is the path schema documented and safe against untrusted identifiers?
- Is the file format stable, versioned, and readable without importing runtime
  hardware dependencies?
- Can a biologist browse it by session, sample, timepoint, modality, and
  provenance?
- Can downstream analysis find the raw data and the metadata needed to interpret
  it?
- Is there data Gently uses but does not persist?
- Is there data Gently stores but never reads, displays, exports, or validates?

## Audit Command

Run a first-pass inventory against a Gently3/FileStore root:

```shell
python -m gently.core.datastore_audit D:/Gently3
```

Use JSON output for scripts:

```shell
python -m gently.core.datastore_audit D:/Gently3 --json --output audit.json
```

The command counts session metadata, timelines/events, interaction logs,
snapshots, volumes, sidecars, sample records, projections, perception traces,
debug exports, profile spans, campaign plans, incoming files, and logs. It also
flags obvious browseability/provenance gaps, including missing `session.yaml`,
unreadable YAML, volume TIFFs without `.meta.yaml` sidecars, snapshot TIFFs
without sidecars, and sample directories without `embryo.yaml`.

## Inventory Template

| Data product | Current path/table | Class | Producer | Consumer | Browse need | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| session metadata | `sessions/*/session.yaml` | durable | launcher/session manager | UI, resume, audit | list sessions | check schema version |
| timeline/events | `timeline.jsonl`, `events.jsonl` | durable | event capture | replay, debug export | filter by time/type | standardize event names |
| interaction log | `interaction_log.jsonl` | durable | agent runtime | debug export | inspect chat/tool flow | include profile links |
| embryo/sample state | `embryos/*/embryo.yaml` | durable | marking/calibration/acquisition | tools, UI, resume | browse sample state | generalize beyond embryos |
| volumes/snapshots | `volumes/*.tif`, `snapshots/*.tif` | durable source | acquisition | perception, analysis | preview, export | verify metadata sidecars |
| projections | `projections/*.jpg` | derived | store/perception | UI | preview | mark recomputable |
| perception traces | `traces/*.json`, `predictions.jsonl` | durable derived | perception | UI/debug/eval | inspect reasoning | link to source volume |
| plans/campaigns | `agent/campaigns/*` | durable | plan mode | UI, execution | browse by campaign | align with session data |
| debug bundles | `debug_exports/*` | derived | debug exporter | coding agent | download/share | retention policy |

## Biologist-Facing Browser

A useful data browser should organize by:

- session and experimental intent
- sample or embryo
- timepoint
- modality: overview, lightsheet volume, projection, perception, plan, event
- provenance: acquisition settings, calibration, exposure, software version,
  operator action, and agent decision

The browser should distinguish raw source data from derived previews and should
always expose the raw file path/export path for analysis outside Gently.

## Gently4 Decision Criteria

Stay on Gently3 and migrate incrementally if:

- path schemas can be versioned in place
- all durable data can be discovered from `sessions/`
- missing metadata can be added as sidecars without breaking existing sessions
- the UI can browse the store without special-case crawlers

Define a Gently4 API if:

- durable data are split across incompatible roots
- old sessions cannot be safely migrated or indexed
- common queries require scanning many large files
- sample abstractions cannot generalize without changing the store contract
- provenance links between raw data, perception, plans, and operator actions are
  not representable in the current layout

## Safety Tie-In

The path and YAML hardening in this PR should remain part of any future
datastore design. A biologist-facing browser or migration API cannot be trusted
unless user-controlled identifiers stay inside the store root and legacy files
fail closed when they contain unsafe constructors.
