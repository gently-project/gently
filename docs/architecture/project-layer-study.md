# The project layer — a study

*2026-10-02. A design study, not a spec. Written against `development` at
7976e6e6 from a read of the plan, run, document and UI code; every claim about
today's behaviour carries a path. The proposal and the open decisions at the end
are for Kesavan to accept, change or throw out.*

## The ask

Make the **project** the top layer. Inside a project live **plans**, some
generated the way plans are generated today (plan mode, the agent), some added
as **runs** the operator sets up ad hoc or by hand, simply. A project also
holds **documents**: protocols, papers, notes, files from outside.

## 1. What exists today

### 1.1 Three things are called a plan

```
   "plan" in the agent's memory          "plan" on the Operate pane          "plan" of a session
   ───────────────────────────────       ──────────────────────────         ──────────────────────
   Campaign  (root = the goal)           Acquisition plan                   Operation plan
     └ Campaign (child = phase)          "what to run", one sentence:         └ Tactic ×N  (op_…/seed_…)
         └ PlanItem ×N                   cadence · channels · endings ·        kind, state, scope,
             type imaging|bench|…        slices · exposure · laser · DIC       structure, live{started,
             ImagingSpec / BenchSpec                                          ended, acquired}
             references[], session_ids[] saved as a Template ("tactic")
                                         in the tactic library
   agent/campaigns/{id}_{slug}/          sessions/{s}/acquisition.yaml       agent/operation_plans/{sid}.yaml
     campaign.yaml                       (ONE per session, overwritten        agent/tactic_library/{id}.yaml
     plan/current.yaml                    on every Start)
     plan/history/*.yaml
     templates/*.yaml
   written by: 27 plan-mode tools        written by: Operate Start route,      written by: Start route (seed),
   read by: Plans tab, Home, Operations   tactic executor; NOT by the          run-tactic, agent tools,
                                         agent's start_adaptive_timelapse     close_timelapse_tactics
```

Sources: `gently/harness/memory/model.py` (`Campaign` :98, `PlanItem` :273,
`ImagingSpec` :200), `gently/harness/memory/file_store.py`,
`static/js/acquisition-plan.js`, `gently/core/file_store.py:611`,
`gently/app/orchestration/tactic_executor.py`.

### 1.2 A run has no identity

A run is the in-memory state of the one `TimelapseOrchestrator`
(`gently/app/orchestration/timelapse.py`, 3769 lines), checkpointed to **one**
`timelapse.yaml` per session, overwritten every acquisition, next to **one**
`acquisition.yaml`, overwritten every Start. Two Starts in a session leave two
tactic cards and one set of files. Volumes keep numbering across runs. Events in
`timeline.jsonl` carry a session id, never a run id. How a run ended
(stopped / completed / failed / interrupted) is in the one `timelapse.yaml`.

A run cannot exist without a session. It can start without the agent (pane →
route → orchestrator) and without a plan item (Operate never touches plan
items). What a run knows about why it ran: `acquisition.yaml.{mode, tactic_id,
library_id, name}` and a seeded tactic whose rationale reads "Started from the
Operate Run step." Plan linkage stops at the session.

Single-volume acquisitions leave no plan, tactic or run trace at all.

### 1.3 Sessions are flat; grouping lives in the agent's memory

```
                 FileStore (sessions/)                    FileContextStore (agent/)
   ┌────────────────────────────────────┐     ┌──────────────────────────────────────────────┐
   │ sessions/_index.yaml               │     │ campaigns/{c}/campaign.yaml  session_ids: [] │ ← written empty,
   │ sessions/{date}_{slug}_{id8}/      │     │                                              │   never appended
   │   session.yaml  (no project field) │     │ campaigns/{c}/plan/current.yaml              │
   │   acquisition.yaml  timelapse.yaml │     │   PlanItem.session_ids[] ──────────────────┐ │ ← the item-level link
   │   embryos/  ui-replay/  removed/   │     │                                            │ │
   └────────────────────────────────────┘     │ session_intents/{sid}.yaml campaign_ids[] ─┼─┤ ← the session-level link
                      ▲                       │                                            │ │
                      └─────────────────────── ┼ ──────────────────────────────────────────┘ │
                                              │ projects/{id}_{slug}.yaml   ← dir created at every start,
                                              │                               Project(description, campaign_id,
                                              │                               status): writer has no callers
                                              └──────────────────────────────────────────────┘
```

Three stores already group sessions three ways, and the fourth (`campaign.yaml.
session_ids`) is written empty. ENTITY-EVOLUTION warned about exactly this when
the ELN branch proposed `Experiment.arms[].session_ids[]` as a fifth.

The word **project** exists in code as a dormant dataclass *under* Campaign
(`model.py:130`, `file_store.py:717`), with no tool, route, UI, command or test,
and appears in the web UI zero times. The de facto top level is the root
Campaign (`get_root_campaigns`), with phases as child campaigns and plan items
as leaves. In the operator's vocabulary that root is the project.

### 1.4 Documents

There is no document. Specifically:

- No upload route, no `attachments/`, `protocols/` or `exports/` directory.
- Paper text from `read_paper` and the citation blocks from `search_literature`
  live only in `conversation.json`. The one durable citation is
  `PlanItem.references[]`, rendered as a bibliography in the campaign Doc view.
- `export_plan` returns markdown to the chat; nothing is written to disk.
- Notes (`gently/harness/memory/notebook.py`) carry `strains[]`, `embryos[]`,
  `sessions[]`, `threads[]`, `artifacts[]` (store pointers, never copied), but
  no project or campaign facet; the only production writer is `record_note`,
  kind fixed to observation; the agent has no tool to read the notebook.
- Ingestion (`/ingest paper.pdf`, 498 lines, 919a3228) was built and deleted
  (00f56b38). `onboarding.apply_ingestion_to_context` is dead code.
- The ELN branch (PR #77, open since July) adds Strain, Experiment, Hypothesis
  and Result as claims with prose, not files.

What *is* on disk and document-like: calibration plots and frames per embryo,
`timelapse.mp4`, `summary.yaml`, the settings history, the recordings. The
reveal mechanism (#221, `gently/ui/web/routes/reveal.py`) opens any of sixteen
kinds of store-resolved path in the file manager or Fiji; adding a kind is one
`WHAT` entry and one `resolve` branch.

### 1.5 The UI

Eleven tabs in three rail groups. The Plans tab (`campaigns.js`, 1890 lines)
shows the campaign tree in six views with an item inspector that can edit the
imaging spec inline and link or unlink a session; everything structural is
agent-only, and there is no "New plan" or "New campaign" control anywhere
(US-06 and US-35 gaps, `docs/user-stories/STATUS.md`). Home's "Recent plans"
lists the top five root campaigns. The gate knows sessions and nothing above
them. Sessions, Home and the gate show no plan linkage; the Operations tab shows
the current session's tactic cards and a "Linked plans" panel.

## 2. The proposal

### 2.1 One sentence

**The root Campaign is the Project.** Rename and promote it, keep phases and
plan items under it, give runs an identity and a home inside sessions, give
sessions a project, and give the project a documents folder. Delete the dormant
`Project` dataclass to free the name.

### 2.2 Entity model

```
                              ┌──────────────────────────────────────────┐
                              │ PROJECT      (= today's root Campaign)   │
                              │ name · question · strain(s) · status     │
                              │ notes[]  documents[]  plan  sessions[]   │
                              └───┬───────────────┬───────────────┬──────┘
                                  │               │               │
                   ┌──────────────▼──┐      ┌─────▼──────┐  ┌─────▼──────────────────┐
                   │ PLAN            │      │ DOCUMENTS  │  │ SESSIONS               │
                   │ sections (= the │      │ protocol   │  │ session.yaml.project_id│
                   │ child campaigns)│      │ paper      │  │   └ RUNS  r01, r02, …  │
                   │  └ PlanItem ×N  │      │ figure     │  │       acquisition.yaml │
                   │    origin:      │      │ data       │  │       timelapse.yaml   │
                   │      agent      │◄─────┤ link/DOI   │  │       run.yaml:        │
                   │      manual ────┼──────┼────────────┼──┼──►   plan_item_id      │
                   │    ImagingSpec  │      │ about: [..]│  │       origin, ended    │
                   │    references[] │      └────────────┘  └────────────────────────┘
                   └─────────────────┘
                   NOTES (notebook) gain a projects[] facet, beside strains/sessions/threads.
```

Two origins, one shape. A plan item written by the agent in plan mode and a run
the operator set up on the Operate pane become the same thing in the project:
a `PlanItem` of type imaging with an `ImagingSpec`, tagged `origin: agent` or
`origin: manual`. The pane's acquisition plan already maps onto the spec:

| Acquisition plan (pane) | ImagingSpec (plan item) |
|---|---|
| `cadence_s` / `interval` | `interval_s`, `adaptive_intervals` |
| `num_slices`, `exposure_ms` | same names |
| `laser_config`, `laser_powers` | `laser_wavelength_nm`, `laser_power_pct` |
| `stop_condition`, `stop_conditions` (per embryo) | `stop_condition`, `target_window` |
| `monitoring_mode` | `detectors[]`, `pre_terminal_speedup` |
| `dic{…}` | new: `dic` block (today the spec has none) |
| `embryo_ids`, `scope` | `num_embryos` (count), run-level: which |

The sentence the pane already speaks ("every 90 s, two channels, until
hatching") is the manual plan item's title.

### 2.3 Storage

```
GENTLY_STORAGE_PATH/
  sessions/{date}_{slug}_{id8}/
    session.yaml            + project_id, name (the gate or the first filing sets it)
    runs/                   NEW — a run is a folder, never overwritten
      r01/
        run.yaml            id, started_at, ended, ended_at, origin (operate|library|agent|plan),
                            plan_item_id, project_id, tactic_id, sentence
        acquisition.yaml    what this run was asked to do
        timelapse.yaml      how far it got (the checkpoint, moved here)
      r02/ …
    acquisition.yaml        kept as "the current run", a copy of runs/<latest>/ — for resume and
    timelapse.yaml          every reader that exists today; retire once readers move
    embryos/ … ui-replay/ … removed/ …
  agent/
    campaigns/{id}_{slug}/  unchanged on disk; a root campaign IS a project
      campaign.yaml         + kind: project (roots) · question · strains[] · status
      plan/current.yaml     PlanItem + origin: agent|manual
      plan/history/  templates/
      documents/            NEW
        documents.yaml      index: id, title, kind, path|url, citation?, added_by, added_at, about[]
        {id}_{slug}.pdf …   files copied in (small) — large or remote things stay as path/url entries
    notebook/notes/*.yaml   Note + projects[]
    projects/               DELETED with the dormant dataclass
```

Why not move `agent/campaigns/` to `agent/projects/`: every reader of the path
would change for no behaviour, and the rename of the *word* happens in the API,
the tools and the UI. A later physical move is a one-time migration if wanted.

Why `session.yaml.project_id` is the truth of membership: it is readable by the
gate, Home and the Sessions tab without the agent store, it is one place, and
it lets `session_intents.campaign_ids` and `campaign.yaml.session_ids` become
derived or go away. `PlanItem.session_ids[]` stays as the item-level link, since
a session can serve several items.

### 2.4 The Projects tab

The Plans tab becomes the Projects tab. Same content id, same module, a project
header and three sections.

```
┌ Gently · 4acb4c47 ⧉ 📁                              [● Gently is asking…]  ⌨ ⚙ ☾ ● Scope online ┐
├──────────┬───────────────────────────────────────────────────────────────────────────────────────┤
│ NOW      │  Hatching timing under temperature stress                        OIS·N2 · active ▾  │
│ Home     │  "Does 20 → 25 °C shift the twitching-to-hatching interval?"      since 2026-09-12 │
│ Operat.  │  ┌ Plan ──────┐┌ Runs (7) ─┐┌ Documents (4) ┐┌ Notes (12) ┐                        │
│ Embryos  │  └────────────┘└───────────┘└───────────────┘└────────────┘                        │
│ LIBRARY  │  ┌──────────────────────────────────────────────────────────────────────────────┐  │
│ Projects │  │ Plan        Doc · Graph · Board · Decide · Matrix · Timeline      v3 ▾ Print │  │
│ Sessions │  │                                                                              │  │
│ Notebook │  │ 1 Baseline at 20 °C                                            done 3/3     │  │
│ Gallery  │  │   1.1 ● 6 embryos · every 90 s · 488 · until hatching     agent    2 runs   │  │
│ SYSTEM   │  │   1.2 ● repeat                                            agent    1 run    │  │
│ Devices  │  │ 2 Shift to 25 °C                                               in progress  │  │
│ Calibr.  │  │   2.1 ○ 6 embryos · every 60 s · 488+561 · until hatching  agent    —       │  │
│ Logs     │  │   2.2 ◐ quick look, 2 embryos · every 30 s · 12 timepoints manual  1 run    │  │
│ Settings │  │                                              [ + add a run by hand ]  (US-07) │  │
│          │  └──────────────────────────────────────────────────────────────────────────────┘  │
└──────────┴───────────────────────────────────────────────────────────────────────────────────────┘

  Runs                                                    Documents
  ┌─────────────────────────────────────────────────┐    ┌──────────────────────────────────────┐
  │ date      session   sentence            ended   │    │ ▣ Protocol: mounting on agar pads    │
  │ 09-29 21:10 36ed5769 6 emb · 90 s · 488  stopped│    │   protocol · pdf · 2 pages      📁   │
  │           ↳ plan 1.1 · live · advanced diag.    │    │ ▣ Moyle et al. 2021 (PMID:…)         │
  │ 09-30 09:02 4acb4c47 2 emb · 30 s · 12 tp done  │    │   paper · link · cited by 2.1        │
  │           ↳ plan 2.2 (manual)                   │    │ ▣ hatching-times-batch1.csv          │
  │ 10-01 …                                         │    │   data · from runs 09-29, 09-30      │
  └─────────────────────────────────────────────────┘    │ [ + add a file ] [ + add a link/DOI ]│
                                                         └──────────────────────────────────────┘
```

Rules it respects (`docs/architecture/PANELS.md`): one subject per surface, the
run and document rows are panels mounted here and reusable on Home and in the
Sessions tab, every value is read back from the store, nothing is remembered in
the browser.

Home: "Recent plans" becomes "Projects" with name, done count and last run.
Gate: a quiet project picker beside the session radio group; "A new session"
can be "in <project>". Strip: a project chip, present only when the session has
one. Operate: the Start sentence ends "in <project>" when the session has one,
and a run started in a session without one gets a one-line "file under…" on its
tactic card afterwards.

### 2.5 Flows

**A. The agent plans, the rig runs (today's path, now filed)**

```
plan mode ─ create_project ─ create_plan_item ×N ─ propose_plan ─ exit
  → resolve_plan_context picks the one unblocked imaging item
  → execute_plan_item → orchestrator.start
      → sessions/{s}/runs/r01/{run.yaml origin=plan plan_item_id=2.1 project_id=P, acquisition.yaml}
      → session.yaml.project_id = P        (if unset)
      → PlanItem 2.1: status in_progress, session_ids += s
run ends → run.yaml.ended = completed|stopped|failed|interrupted → item outcome as today
```

**B. The operator sets up a run by hand (new)**

```
Operate › Acquisition: form → sentence → Start                     (unchanged)
  → POST /api/devices/timelapse/start (+ project_id if the session has one)
  → runs/r02/{run.yaml origin=operate, acquisition.yaml}
  → if session.project_id and no active plan item:
        create PlanItem(type=imaging, origin=manual, title=sentence,
                        spec=ImagingSpec.from_acquisition(plan), session_ids=[s])
        run.yaml.plan_item_id = that item
     else: run.yaml.plan_item_id = the active item
Afterwards, from the Runs list or the tactic card: "file under…" moves the run
and its item to another project; "unfile" turns the item into a plain run record.
```

The pane does not change. The project's plan simply ends up saying what was
actually run, and a run set up at the microscope is not a second-class citizen
to one the agent wrote.

**C. A document joins the project (new)**

```
Projects › Documents › add a file     → POST /api/projects/{p}/documents  (multipart, require_control,
                                         size cap) → copied to documents/{id}_{slug}.ext, indexed
Projects › Documents › add a link/DOI → POST …/documents {url|doi, title?}
                                         → PubMed/Unpaywall lookup that search_literature already does,
                                           now PERSISTED as citation on the index entry
From plan mode: search_literature / read_paper results offered as "keep this in the project"
                                         → same index entry; the extracted text saved beside it (.txt)
                                           so notebook_ask and plan mode can cite from disk, not chat
Reveal: kind "project" opens documents/; kind "document" opens the file (one WHAT entry each).
Notes: record_note(project=…) and the Notebook tab filter by project.
```

### 2.6 Agent tools

Keep the 27 plan tools. Add five, all thin:

| Tool | Does |
|---|---|
| `create_project` | the root `create_campaign` with project fields; `create_campaign(parent_id)` stays for sections |
| `file_run_under_project` | sets `run.yaml.project_id`/`plan_item_id`, creates the manual item if none |
| `add_document` | by path, URL or DOI; persists citation; optional `about[]` |
| `list_documents` / `read_document` | index, or the saved text of one document |
| `record_note` gains `project=` | and the Notebook gains the facet |

And one deletion: `plan_mode/tools` stop leaking into run mode
(`gently/app/tools/__init__.py:9` imports them; `manager.py:181` passes the
unfiltered registry), which is unrelated to projects but found on the way.

## 3. Migration

1. Root campaigns get `kind: project` on first read (lazy, idempotent).
2. `session.yaml.project_id` is backfilled from `session_intents/{sid}.yaml.
   campaign_ids[0]` where it exists, otherwise from the first `PlanItem.
   session_ids` match; the rest stay unfiled.
3. Existing `acquisition.yaml` + `timelapse.yaml` of a session become
   `runs/r01/` on first open; the top-level copies stay until every reader
   moves (resume, the gate's "a run was interrupted", `_reawaken_operate_tactics`).
4. `agent/projects/` and the `Project` dataclass are deleted; `serialization.
   py:37` and `Intentions.projects` go with them.
5. `campaign.yaml.session_ids` and `session_intents.campaign_ids` become
   derived views over `session.yaml.project_id`, then are removed.

## 4. Open decisions

1. **Rename on disk now or later.** The study says later. The cost of now is a
   path change in every reader for no behaviour; the cost of later is the word
   "campaigns" in a folder name.
2. **At most one project per session.** Recommended yes. A session that serves
   two projects is a sign the projects are one; `PlanItem.session_ids[]`
   still lets several items share a session.
3. **Manual runs become plan items automatically.** Recommended yes when the
   session has a project, with "unfile" as the undo, so the plan stays honest
   about what ran. The alternative, a separate runs list never touching the
   plan, keeps the agent's plan pristine and the operator's work invisible to
   it.
4. **Documents copied or linked.** Recommended: copy files under a size cap into
   the project folder so the folder is the project; link large or remote
   things by path or URL. Everything lands in one index either way.
5. **Phases stay as sections.** ENTITY-EVOLUTION proposed `Experiment` as the
   layer between Campaign and Session; the ELN branch built it. With the
   project as the top and sections below, the middle is a child campaign with
   a role, not a new entity. Revisit when a project has arms and replicates
   that sections cannot say.
6. **What the agent may do with documents.** Read when asked, cite in plan
   items, never summarise into learnings unprompted. The deleted ingestion
   capability did the last one.
7. **Who may add and remove.** `require_control` for now, like every write.
   Permissions over projects were already on ENTITY-EVOLUTION's "later" list.

## 5. The smallest first slice

Each line ships on its own and is useful alone.

| # | Slice | Size | Unblocks |
|---|---|---|---|
| 1 | Run identity: `runs/<id>/` with `run.yaml`; `session.yaml.project_id`; readers unchanged | small, storage + tests | everything below |
| 2 | The word: Projects tab label, project header, Home card, `kind: project` on roots, delete the dormant dataclass | small | the operator sees a project |
| 3 | Runs section: list across sessions by `project_id`, with the chips the lists already have (live, advanced diagnostics) | small | runs are findable |
| 4 | Documents: index, add by path and by URL/DOI with persisted citation, two reveal kinds | medium | documents exist |
| 5 | Manual filing: Operate Start under a project creates the manual item; "file under…" on a run | medium | plans say what ran |
| 6 | Gate picker, strip chip, Note facet, the five tools, multipart upload | medium | the rest of the model |

Slice 1 is the one that cannot be skipped: without a run that is a thing with
an id, every later slice is grouping files that overwrite each other.

## Appendix: facts that shaped this

- `Project` dataclass: `gently/harness/memory/model.py:130`; writer
  `create_project` at `file_store.py:717`, zero callers; dir created by
  `_ensure_dirs`.
- Singleton run files: `gently/core/file_store.py:611` (`save_acquisition_plan`),
  `timelapse.py:2451` (`save_state`); `ended` set at :594/:1257/:1317/:2173.
- Session grouping stores: `PlanItem.session_ids` (`model.py:273`),
  `session_intents/{sid}.yaml.campaign_ids` (`file_store.py:876-922`),
  `campaign.yaml.session_ids` written `[]` (`file_store.py:376-387`).
- Plan mode: 27 tools in `gently/harness/plan_mode/tools/`, 3762 lines;
  `propose_plan` renders and mutates nothing; there is no draft or commit state.
- UI: no create-campaign or new-plan control (US-06, US-35); the Plans tab's
  only writes are the spec PATCH and session link/unlink.
- Documents: no upload route; `read_paper` text and `search_literature` citations
  live only in `conversation.json`; ingestion deleted in 00f56b38.
- Reveal: `routes/reveal.py` `WHAT` (16 kinds) + `resolve()`; one entry and one
  branch per new kind.
- The ELN branch (PR #77) and its fold study
  (`docs/superpowers/specs/2026-07-02-planmode-eln-fold-study.md`) recommended
  absorbing Strain, Hypothesis and Result into plan mode and demoting Experiment
  to a phase role; this study is consistent with that and adds nothing from it.
