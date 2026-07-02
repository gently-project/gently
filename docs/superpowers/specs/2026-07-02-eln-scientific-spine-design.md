# ELN Scientific Spine — Strain → Experiment → Hypothesis → Result — Design

Date: 2026-07-02
Status: Approved (design) — implementation planned via writing-plans
Branch: feature/eln-scientific-spine (off #72; PR back into #72)
Origin: `docs/product-ideation/ENTITY-EVOLUTION.md` (Fable's entity-evolution assessment) + Hari Shroff's *Plan for Agentic Microscopy Paper* (6/3/26).

## Problem

gently lets a biologist **drive the hardware** but only **watch the mind**: the agent
holds a near-monopoly on authoring the shared record; the human's only write-path is
dictating to chat. The data model has an **empty scientific middle** — `Campaign` is a
program, `Session` is one run, but nothing expresses "these 6 sessions are 3 replicates
of two arms of one comparison testing a claim." The agent forms `Expectation`s (with
`expected_time` + auto-resolvable status; `gently/harness/memory/_understanding.py`) and
logs `Learning`s, but nothing states the **claim** they bear on or whether it
**survived**. And the most-referenced scientific thing — `strain` — is a bare string on
`ImagingSpec.strain/genotype/reporter` (`gently/harness/memory/model.py:200`),
`BenchSpec`, `Note.strains[]`, `ground_truth` (a partial `EmbryoInfo.strain` +
`tests/test_embryo_strain.py` already exist).

This spec adds a thin **scientific spine** that turns data-collection into
claim-testing and gives the human a first-class, co-authored write-path.

## Goals

- **Strain** record (genotype, markers, stock, organism ref) that everything resolves
  to — with bare-string back-compat.
- **Experiment** — the controlled-comparison unit (arms × replicates × controls)
  between Campaign and Session; groups Sessions into an analyzable design.
- **Hypothesis** — a falsifiable claim with status, consolidating the diffuse
  Expectation/Question/Learning triad around a testable statement.
- **Result** — a quantitative/derived finding (distinct from a prose Learning) with
  method + provenance; the object a figure or paper reads.
- Close an **assisted claim-testing loop** on the *existing* `Expectation.resolve` +
  `ground_truth` (agent proposes, human confirms).
- Co-authored: the human **or** the agent can create/edit any of these.

## Primary near-term use case: in-ELN perception annotation → HuggingFace

The active driver is the **embryo stage-classification** project. `gently-perception`
(Anthropic-built perceiver, a separate pip dependency) runs on live embryos and emits
per-timepoint stage predictions (`predictions.jsonl` + `traces/`). Today, turning those
into training data happens in a **separate, disconnected annotator** (`gently/dataset/`
— `aggregator.py`, `embryo_dataset.py`, `explorer_server.py`, `schema.py`;
`stage_annotator.py`; see `docs/PERCEPTION_V2_IMPROVEMENT_STRATEGY.md`) — the human's
feedback lives *outside* the live session.

The spine's **ground-truth authoring** is the in-ELN mechanism for human feedback to the
data, and it should **converge** that annotator into the session surface rather than
duplicate it. The flywheel:

1. **Predict** — `gently-perception` emits stage predictions on live embryos.
2. **Annotate in-ELN (assisted-human-in-the-loop)** — on the Vitals stage strip the
   human corrects/confirms ground truth by **range** (drag-select); the **agent
   pre-screens** — bulk-proposes high-agreement stretches as ground truth (one range
   confirm) and surfaces ONLY the uncertain/transitional frames for the human to decide.
   The agent narrows; the human confirms. Persists via `set_ground_truth(stage,
   timepoint, annotator)` (`core/file_store.py:1255`), stamped with annotator +
   provenance (the projection/trace it was judged from).
3. **Score** — a `Result` of `kind: accuracy` computes predicted-vs-ground-truth per
   run; the accuracy readout, annotated-count, and few-shot pool update at authoring.
4. **Export → HuggingFace** — see the connector below.

### The HuggingFace connector (approval-gated)

An **Experiment** can be **configured with an export target** — a HuggingFace dataset
repo (default `pskeshu/gently-perception-benchmark`). On the human's **approval**, the
accumulated {projection/volume ref, model prediction, human ground truth, provenance,
strain/organism} formats into the dataset schema (reuse `gently/dataset` aggregator /
`benchmarks/perception/ground_truth.py`) and pushes via `huggingface_hub` /
`datasets.push_to_hub`. Design constraints:
- **Approval gate:** a push is a specimen-external publish — it uses the same
  assisted-approval posture as hardware actions (`require_control` + an explicit
  confirm; never automatic). The agent may *prepare* the export and *propose* the push;
  the human approves.
- **Token from env:** `HF_TOKEN` (assume present in production). Absent token ⇒ the
  connector disables with a clear "set HF_TOKEN" state (never a silent failure).
- **Config lives on the Experiment:** `export = {target: "hf", repo, split, revision}`.
- **Incremental + provenant:** each push records what was exported (which annotations,
  which revision) so re-pushes are diffs, and the dataset carries provenance back to the
  session/embryo/annotator.
- **Companion detail:** the exact dataset feature-schema + the migration of the
  standalone `gently/dataset` tooling is an implementation detail carried in the plan;
  this spec fixes the contract (approval-gated, env-token, per-experiment target).

This makes the loop bidirectional: the model's live calls become the human's annotation
queue; the human's corrections become the model's next training set — without leaving
the notebook.

## Seed / default programs (real data, version-controlled)

Ship the repo with **real research programs** (not stubs) as seed `Campaign →
Experiment → Hypothesis` instances under `seed/programs/`, loadable into a fresh gently.
Purpose: (a) shape a *reusable* gently by building against actual cases; (b) real
notebook data to work with instead of stubs; (c) development seriousness. They are the
spine's dogfood + its best validation. The four (from Hari's paper plan + collaborator
notes):

1. **Embryo stage classification** — nuclear (+ bright-field fusion) staging with
   `gently-perception`; hatching-detection subproblem (high-cadence to catch hatching).
   The perception-annotation→HuggingFace flywheel above is its engine.
2. **Temperature → hatching-time distributions (K-pump thermo strain)** — Richard's
   strain targets the potassium pumps so that at **25 °C the embryo stops twitching**
   (3-fold stage). The agent uses **thermo-cycling** creatively (paralysis-free imaging
   windows) and studies hatching-time *distributions* and how imaging/thermalization
   perturb them. Exercises the temperature setpoint + (future) Actuator axis.
3. **Mutant screen** — mixed WT + mutant populations; the agent reports which embryo is
   which. Exercises multi-embryo roles + classification + reporting.
4. **Dopaminergic neuronal outgrowth ("catching outgrowth")** — the novel target
   (Richard/`proposals/janelia/danienella`): image the *developing* neuron, not its
   final state. `dat1` onset (~3-fold) marks the dopaminergic neuron and opens the
   outgrowth window; the agent runs **low-cadence monitor until the signal appears, then
   switches to high-cadence** (expression-triggered differential acquisition;
   `gently/app/detectors/dopaminergic_signal.py` already exists), quantifying outgrowth
   timing toward a dependency-map of neural-architecture development. Test case: an early
   slow ventral-nerve-cord neuron vs a later `dat1` neuron.

Real strains available in-repo/notes (e.g. OH904 `rab-3p::GFP` pan-neuronal, otIs355,
unc-6(ev400) crosses; the K-pump thermo strain). Seed programs instantiate real Strain
records referencing these.

## Non-goals (YAGNI)

- `Setpoint → typed Actuator` generalization — its own later spec (the temperature seed
  program will motivate it).
- `Embryo → Specimen` rename — `SAMPLE_TERM` already covers the human-facing need.
- Modality/Device capability layer; multi-tenant (Team/Permission/Booking) — deferred to
  the cloud-venture track.
- Re-inventing the organism model — it is already the `gently.organisms` plugin; Strain
  references it.
- Full migration of the standalone `gently/dataset` annotator — the ELN owns in-session
  annotation + the export trigger; the export pipeline + tool migration are planned
  detail, not this design.

## Entities & schemas

File-based under `agent/` (`FileContextStore` conventions; no SQLite). **All fields
optional unless (req).** Every entity is an **optional overlay** — nothing in the
existing flow requires one.

**Strain** — `agent/strains/{id}.yaml`: `id`, `name` (req), `genotype`, `markers[]`,
`background`, `source_lab`, `organism_ref` (→ `gently.organisms` key), `stock`
{`thawed`,`frozen`,`notes`}, `created_at`, `author`. `ImagingSpec.strain/genotype/reporter`,
`BenchSpec.strains[]`, `Note.strains[]`, `ground_truth`, and `EmbryoInfo.strain` gain
resolution to a Strain `id`; an unrecognized string stays valid (display-only). No forced
migration.

**Experiment** — `agent/experiments/{id}.yaml`: `id`, `title` (req), `campaign_ref`,
`hypothesis_refs[]`, `arms` [{`name`, `strain_ref`, `condition`, `session_ids[]`}],
`controls[]`, `replicate_of`, `export` {`target`,`repo`,`split`,`revision`}, `notes`,
`status`, `created_at`, `author`. Reuses the campaign hierarchy + session-link plumbing
(`FileContextStore.get_sessions_for_campaign`, `get_campaign_ids_for_session`). A Session
belongs to zero or one Experiment arm.

**Hypothesis** — `agent/hypotheses/{id}.yaml`: `id`, `statement` (req), `status`
(`proposed`|`supported`|`refuted`|`inconclusive`), `predictions` [{`target`,`expected`,
`expectation_ref?`}], `experiment_refs[]`, `author` (`human`|`agent`), `basis[]`,
`created_at`.

**Result** — `agent/results/{id}.yaml`: `id`, `kind` (`measurement`|`derived`|
`accuracy`), `value`|`table`, `method`, `inputs[]` (sessions/embryos/predictions/
ground_truth), `experiment_ref`, `hypothesis_ref`, `status` (`draft`|`final`),
`provenance` {`author`,`ts`,`derived_from`}.

## Data flow — the assisted scoring loop

When an Experiment's Sessions complete **and** a bound `Expectation`'s `expected_time`
passes (or `ground_truth` lands), the **agent computes a candidate `Result`** (hatch-rate
per arm, transition timing, predicted-vs-GT accuracy) and **proposes a Hypothesis
verdict**; both surface for the human to **confirm or edit**. Confirmed Results persist +
may promote to a calibrated `Learning`. Manual authoring + verdicts always available —
automation assists, never decides.

## Authorship (co-authored)

Human and agent are symmetric writers. Human: forms/composers + contextual seeds. Agent:
new tools (`create_experiment`, `author_hypothesis`, `record_result`,
`link_session_to_arm`, `configure_export`) alongside the campaign/plan tools. `author`
stamped on every record.

## UI surfaces

Reuse the Plans/Operations family — no new top-level tab unless it earns one.
**Experiments** in the campaign navigator/inspector (arms, replicates, member sessions,
hypotheses + status, export config + push button). **Strain** a light record view +
clickable chip everywhere strain appears (reverse links). **Hypothesis + Result** on the
Experiment + cross-linked into the Notebook (a confirmed verdict posts a FINDING note).
**Ground-truth authoring** on the Vitals stage strip (range drag-select + assisted
batch-confirm).

## Error handling / edges

Bare-string strain stays valid; optional membership (orphan Session = today's behavior);
cold-start (zero entities ⇒ identical to now); incomplete-input Result stays `draft`;
deleting a referenced Strain dereferences to display-string (no cascade); missing
`HF_TOKEN` disables the connector with a clear state.

## Testing

- Store round-trip + back-compat unit tests per entity; a scoring test on fixtures
  (Expectation + ground_truth → candidate Result → proposed verdict); HF connector
  tested with a mocked `push_to_hub` + a token-absent path.
- **New `US-` story flows** (the repo's audit paradigm, once the `tools/ui_crawler`
  harness lands on the base via #76): `strain-record`, `create-experiment`,
  `link-session-to-arm`, `author-hypothesis`, `record-result`, `annotate-ground-truth`,
  `configure-hf-export` — each a verdict + trace + screenshot in the baseline-diff suite.

## Phasing (per Fable's sequencing)

1. **Strain record** + back-compat resolution (keystone).
2. **Experiment** (arms/replicates/controls; Session grouping; export config).
3. **Hypothesis + Result** + the assisted scoring loop.
4. **HF connector** (approval-gated push) — can co-develop with the annotation UI.

**The annotation flywheel can lead.** The perception-annotation loop (ground-truth
range-authoring + assisted batch-confirm + `accuracy` Result + a first HuggingFace
export) needs only Embryo/Prediction/`ground_truth` — independent of Strain/Experiment —
and is the active project, so it can be built first. Strain→Experiment later enriches it
with per-strain / per-experiment dataset slices.

## Open items

- Experiments' own nav entry vs inside Plans (decide in phase-2 UI).
- The agent's candidate-Result computation set (phase-3 detail).
- Exact HF dataset feature-schema + `gently/dataset` convergence (planned detail).
