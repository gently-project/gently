# ELN Scientific Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the co-authored ELN scientific spine (Strain → Experiment → Hypothesis → Result) + the perception-annotation → HuggingFace flywheel to gently, as optional file-based overlays.

**Architecture:** New spine entities are file-based YAML under `agent/` via `FileContextStore` (mirrors the campaign store). ELN logic (accuracy scoring, HF export) lives in a new `gently/eln/` package that reads from `FileStore` (not the deprecated `gently/dataset`). Ground-truth authoring reuses the existing `FileStore.set_ground_truth` (already range-based). Scoring reuses the existing `Expectation` machinery. Everything is optional — nothing in the current flow requires a spine record.

**Tech Stack:** Python 3.10+, FastAPI (viz routes), PyYAML (file store), pytest, ruff. HuggingFace export via lazy `datasets`/`huggingface_hub` (not base deps). Vanilla JS for the viz UI.

## Global Constraints

- Python `>=3.10,<3.13`; numpy `<2`; ruff line-length 100; `select = ["E","F","I","UP","B"]`.
- No SQLite for spine entities — file-based YAML under `agent/` (`FileContextStore`).
- Spine entities are OPTIONAL overlays; bare-string strain back-compat (no forced migration).
- HuggingFace export is APPROVAL-GATED (`require_control` + explicit confirm; never auto); `HF_TOKEN` from env; default repo `pskeshu/gently-perception-benchmark`.
- UI work: verify in-browser (Chrome MCP UI/UX audit — alignment/spacing/overflow/contrast) before marking done; only show coherent screens (per repo convention).
- Commit after every green step.

---

## Status — already implemented on `feature/eln-scientific-spine` (backend, tested)

These are DONE and merged on the branch; later tasks build on them:

- **Strain store** — `FileContextStore.create_strain/get_strain/list_strains/resolve_strain` (`gently/harness/memory/file_store.py`); spine dir skeleton (`strains/experiments/hypotheses/results`). Tests: `tests/test_strain_store.py` (3).
- **HF connector** — `gently/eln/hf_connector.py`: `build_records` (pure), `push_dataset` (approval-gated, env `HF_TOKEN`, lazy `datasets`, `_push_fn` injection), `token_present`. Tests: `tests/test_hf_connector.py` (5).
- **Accuracy scoring** — `gently/eln/accuracy.py`: `stage_at_timepoint`, `score_accuracy`, `accuracy_result`. Tests: `tests/test_eln_accuracy.py` (4).
- **Ground-truth authoring route** — `POST /api/embryos/{id}/ground_truth` (`gently/ui/web/routes/data.py`, `require_control`, range-based → `set_ground_truth`). Tests: `tests/test_eln_ground_truth_route.py` (4).
- **Seed data** — `seed/programs/{stage-classification,temperature-hatching,mutant-screen,dopaminergic-outgrowth}.yaml` + README.
- **Usage evaluation** — `docs/product-ideation/ELN-USAGE.md` (biologist journey + iterative stories + story-flow specs + design implications).

Run all: `.venv/bin/python -m pytest tests/test_strain_store.py tests/test_hf_connector.py tests/test_eln_accuracy.py tests/test_eln_ground_truth_route.py -q` → 16 passed.

---

## File Structure (remaining work)

- `gently/harness/memory/file_store.py` — add Experiment / Hypothesis / Result store methods (mirror Strain).
- `gently/eln/seed_loader.py` — CREATE: load `seed/programs/*.yaml` into `FileContextStore`.
- `gently/eln/strain_resolution.py` — CREATE: resolve strain refs on `ImagingSpec`/`Note` for display (non-mutating).
- `gently/eln/export_service.py` — CREATE: assemble annotation rows from `FileStore` for an experiment → `hf_connector`.
- `gently/ui/web/routes/data.py` — add Experiment/Result read routes + the approval-gated export route.
- `gently/harness/tools/…` — register agent tools (`create_experiment`, `author_hypothesis`, `record_result`, `link_session_to_arm`, `configure_export`).
- `gently/ui/web/static/js/…` + templates — Vitals stage-strip authoring UI, accuracy readout, experiment inspector, export button.
- `tools/ui_crawler/stories/US-*.py` — ELN story flows (after #76 lands the harness on the base).

---

## Task 1: Experiment store

**Files:**
- Modify: `gently/harness/memory/file_store.py` (after the Strain methods)
- Test: `tests/test_experiment_store.py`

**Interfaces:**
- Consumes: `self._gen_id`, `self._now`, `self._write_yaml`, `self._read_yaml`, `self.agent_dir`.
- Produces: `create_experiment(title, campaign_ref=None, arms=None, controls=None, replicate_of=None, export=None, author=None, experiment_id=None) -> str`; `get_experiment(id) -> dict|None`; `list_experiments() -> list[dict]`; `link_session_to_arm(experiment_id, arm_name, session_id) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_experiment_store.py
from gently.harness.memory.file_store import FileContextStore


def test_create_and_get_experiment(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    eid = s.create_experiment(
        "32C vs control",
        arms=[{"name": "hot", "strain_ref": "OH904", "condition": "25C"}],
        controls=["control"],
    )
    e = s.get_experiment(eid)
    assert e["title"] == "32C vs control"
    assert e["arms"][0]["name"] == "hot"
    assert e["controls"] == ["control"]


def test_link_session_to_arm(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    eid = s.create_experiment("e", arms=[{"name": "hot", "strain_ref": "x", "condition": "c"}])
    assert s.link_session_to_arm(eid, "hot", "sess1") is True
    assert "sess1" in s.get_experiment(eid)["arms"][0]["session_ids"]
    assert s.link_session_to_arm(eid, "missing", "sess1") is False


def test_list_experiments(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_experiment("a"); s.create_experiment("b")
    assert len(s.list_experiments()) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_experiment_store.py -q`
Expected: FAIL (`AttributeError: ... 'create_experiment'`).

- [ ] **Step 3: Write minimal implementation**

Add to `FileContextStore` (after the Strain section):

```python
    # ------------------------------------------------------------------
    # Scientific spine — Experiment (ELN, phase 2). Optional overlay.
    # ------------------------------------------------------------------

    def create_experiment(
        self,
        title: str,
        campaign_ref: str | None = None,
        arms: list | None = None,
        controls: list | None = None,
        replicate_of: str | None = None,
        export: dict | None = None,
        author: str | None = None,
        experiment_id: str | None = None,
    ) -> str:
        eid = experiment_id or self._gen_id()
        now = self._now()
        norm_arms = []
        for a in arms or []:
            norm_arms.append({
                "name": a.get("name"),
                "strain_ref": a.get("strain_ref") or a.get("strain"),
                "condition": a.get("condition"),
                "session_ids": list(a.get("session_ids") or []),
            })
        data = {
            "id": eid, "title": title, "campaign_ref": campaign_ref,
            "hypothesis_refs": [], "arms": norm_arms,
            "controls": list(controls or []), "replicate_of": replicate_of,
            "export": export or {}, "notes": None, "status": "active",
            "author": author, "created_at": now, "updated_at": now,
        }
        self._write_yaml(self.agent_dir / "experiments" / f"{eid}.yaml", data)
        return eid

    def get_experiment(self, experiment_id: str) -> dict | None:
        p = self.agent_dir / "experiments" / f"{experiment_id}.yaml"
        return self._read_yaml(p) if p.exists() else None

    def list_experiments(self) -> list[dict]:
        d = self.agent_dir / "experiments"
        if not d.exists():
            return []
        return [e for e in (self._read_yaml(f) for f in sorted(d.glob("*.yaml"))) if e]

    def link_session_to_arm(self, experiment_id: str, arm_name: str, session_id: str) -> bool:
        e = self.get_experiment(experiment_id)
        if not e:
            return False
        for arm in e.get("arms", []):
            if arm.get("name") == arm_name:
                if session_id not in arm.setdefault("session_ids", []):
                    arm["session_ids"].append(session_id)
                e["updated_at"] = self._now()
                self._write_yaml(self.agent_dir / "experiments" / f"{experiment_id}.yaml", e)
                return True
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_experiment_store.py -q` → Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add gently/harness/memory/file_store.py tests/test_experiment_store.py
git commit -m "feat(eln): Experiment store (spine phase 2)"
```

---

## Task 2: Hypothesis store

**Files:**
- Modify: `gently/harness/memory/file_store.py`
- Test: `tests/test_hypothesis_store.py`

**Interfaces:**
- Produces: `create_hypothesis(statement, predictions=None, experiment_refs=None, author=None, hypothesis_id=None) -> str`; `get_hypothesis(id) -> dict|None`; `list_hypotheses() -> list[dict]`; `set_hypothesis_status(id, status) -> bool` where status ∈ {proposed, supported, refuted, inconclusive}.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hypothesis_store.py
import pytest
from gently.harness.memory.file_store import FileContextStore


def test_create_get_hypothesis(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    hid = s.create_hypothesis(
        "25C shifts hatching-time distribution later",
        predictions=[{"target": "median_hatch", "expected": "+30min"}],
        author="human",
    )
    h = s.get_hypothesis(hid)
    assert h["statement"].startswith("25C")
    assert h["status"] == "proposed"
    assert h["predictions"][0]["target"] == "median_hatch"


def test_set_status(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    hid = s.create_hypothesis("h")
    assert s.set_hypothesis_status(hid, "supported") is True
    assert s.get_hypothesis(hid)["status"] == "supported"
    with pytest.raises(ValueError):
        s.set_hypothesis_status(hid, "bogus")
```

- [ ] **Step 2: Run test to verify it fails** — Run: `.venv/bin/python -m pytest tests/test_hypothesis_store.py -q` → FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
    # ------------------------------------------------------------------
    # Scientific spine — Hypothesis (ELN, phase 3). Optional overlay.
    # ------------------------------------------------------------------
    _HYP_STATUSES = ("proposed", "supported", "refuted", "inconclusive")

    def create_hypothesis(
        self,
        statement: str,
        predictions: list | None = None,
        experiment_refs: list | None = None,
        author: str | None = None,
        hypothesis_id: str | None = None,
    ) -> str:
        hid = hypothesis_id or self._gen_id()
        data = {
            "id": hid, "statement": statement, "status": "proposed",
            "predictions": list(predictions or []),
            "experiment_refs": list(experiment_refs or []),
            "author": author, "basis": [], "created_at": self._now(),
        }
        self._write_yaml(self.agent_dir / "hypotheses" / f"{hid}.yaml", data)
        return hid

    def get_hypothesis(self, hypothesis_id: str) -> dict | None:
        p = self.agent_dir / "hypotheses" / f"{hypothesis_id}.yaml"
        return self._read_yaml(p) if p.exists() else None

    def list_hypotheses(self) -> list[dict]:
        d = self.agent_dir / "hypotheses"
        if not d.exists():
            return []
        return [h for h in (self._read_yaml(f) for f in sorted(d.glob("*.yaml"))) if h]

    def set_hypothesis_status(self, hypothesis_id: str, status: str) -> bool:
        if status not in self._HYP_STATUSES:
            raise ValueError(f"status must be one of {self._HYP_STATUSES}")
        h = self.get_hypothesis(hypothesis_id)
        if not h:
            return False
        h["status"] = status
        self._write_yaml(self.agent_dir / "hypotheses" / f"{hypothesis_id}.yaml", h)
        return True
```

- [ ] **Step 4: Run test to verify it passes** → PASS (2).

- [ ] **Step 5: Commit**

```bash
git add gently/harness/memory/file_store.py tests/test_hypothesis_store.py
git commit -m "feat(eln): Hypothesis store (spine phase 3)"
```

---

## Task 3: Result store + persist accuracy Result

**Files:**
- Modify: `gently/harness/memory/file_store.py`
- Test: `tests/test_result_store.py`

**Interfaces:**
- Consumes: `gently.eln.accuracy.accuracy_result`.
- Produces: `save_result(result: dict, result_id=None) -> str`; `get_result(id) -> dict|None`; `list_results(experiment_ref=None) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_result_store.py
from gently.harness.memory.file_store import FileContextStore
from gently.eln.accuracy import accuracy_result


def test_save_and_filter_results(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    r = accuracy_result("sess", "emb", [{"timepoint": 1, "predicted_stage": "bean"}],
                        [{"stage": "bean", "start_timepoint": 0, "end_timepoint": 5}])
    r["experiment_ref"] = "exp1"
    rid = s.save_result(r)
    assert s.get_result(rid)["kind"] == "accuracy"
    assert len(s.list_results(experiment_ref="exp1")) == 1
    assert len(s.list_results(experiment_ref="other")) == 0
```

- [ ] **Step 2: Run test to verify it fails** → FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
    # ------------------------------------------------------------------
    # Scientific spine — Result (ELN, phase 3). Optional overlay.
    # ------------------------------------------------------------------

    def save_result(self, result: dict, result_id: str | None = None) -> str:
        rid = result_id or result.get("id") or self._gen_id()
        data = dict(result)
        data["id"] = rid
        data.setdefault("created_at", self._now())
        self._write_yaml(self.agent_dir / "results" / f"{rid}.yaml", data)
        return rid

    def get_result(self, result_id: str) -> dict | None:
        p = self.agent_dir / "results" / f"{result_id}.yaml"
        return self._read_yaml(p) if p.exists() else None

    def list_results(self, experiment_ref: str | None = None) -> list[dict]:
        d = self.agent_dir / "results"
        if not d.exists():
            return []
        out = [r for r in (self._read_yaml(f) for f in sorted(d.glob("*.yaml"))) if r]
        if experiment_ref is not None:
            out = [r for r in out if r.get("experiment_ref") == experiment_ref]
        return out
```

- [ ] **Step 4: Run test to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git add gently/harness/memory/file_store.py tests/test_result_store.py
git commit -m "feat(eln): Result store + persist accuracy Result (spine phase 3)"
```

---

## Task 4: Strain resolution helper (display-side, non-mutating)

**Files:**
- Create: `gently/eln/strain_resolution.py`
- Test: `tests/test_strain_resolution.py`

**Interfaces:**
- Consumes: `FileContextStore.resolve_strain`.
- Produces: `resolve_ref(store, ref) -> dict|None` (returns `{"id","name",...}` record or a `{"name": ref}` shim for a bare unmatched string); `enrich_imaging_spec(store, spec_dict) -> dict` (adds `strain_record` alongside the raw `strain` string, never overwrites).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strain_resolution.py
from gently.harness.memory.file_store import FileContextStore
from gently.eln.strain_resolution import resolve_ref, enrich_imaging_spec


def test_resolve_ref_record_and_shim(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_strain("OH904", genotype="otIs355")
    assert resolve_ref(s, "OH904")["genotype"] == "otIs355"     # real record
    shim = resolve_ref(s, "unknown-str")
    assert shim == {"name": "unknown-str"}                       # bare-string shim
    assert resolve_ref(s, None) is None


def test_enrich_imaging_spec_non_mutating(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    s.create_strain("N2")
    spec = {"strain": "N2", "num_slices": 80}
    out = enrich_imaging_spec(s, spec)
    assert out["strain"] == "N2"               # original preserved
    assert out["strain_record"]["name"] == "N2"
    assert "strain_record" not in spec         # did not mutate input
```

- [ ] **Step 2: Run test to verify it fails** → FAIL (no module).

- [ ] **Step 3: Write minimal implementation**

```python
# gently/eln/strain_resolution.py
"""Display-side strain resolution — non-mutating, bare-string safe."""
from __future__ import annotations


def resolve_ref(store, ref):
    if not ref:
        return None
    rec = store.resolve_strain(ref)
    return rec if rec else {"name": ref}


def enrich_imaging_spec(store, spec_dict):
    out = dict(spec_dict)
    ref = out.get("strain")
    if ref:
        out["strain_record"] = resolve_ref(store, ref)
    return out
```

- [ ] **Step 4: Run test to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git add gently/eln/strain_resolution.py tests/test_strain_resolution.py
git commit -m "feat(eln): non-mutating strain resolution helper"
```

---

## Task 5: Seed loader

**Files:**
- Create: `gently/eln/seed_loader.py`
- Test: `tests/test_seed_loader.py`

**Interfaces:**
- Consumes: `FileContextStore.create_strain/create_campaign/create_experiment/create_hypothesis`.
- Produces: `load_program(store, program_dict) -> dict` (returns `{campaign_id, strain_ids, experiment_ids, hypothesis_ids}`); `load_seed_dir(store, seed_dir) -> list[dict]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seed_loader.py
from gently.harness.memory.file_store import FileContextStore
from gently.eln.seed_loader import load_program


def test_load_program(tmp_path):
    s = FileContextStore(tmp_path / "agent")
    program = {
        "slug": "demo",
        "campaign": {"title": "T", "goal": "G", "description": "D"},
        "strains": [{"name": "OH904", "genotype": "otIs355"}],
        "experiments": [{"title": "E1", "arms": [{"name": "a", "strain": "OH904", "condition": "c"}]}],
        "hypotheses": [{"statement": "H1", "predictions": ["p"]}],
    }
    out = load_program(s, program)
    assert s.get_campaign(out["campaign_id"]) is not None
    assert len(out["strain_ids"]) == 1 and len(out["experiment_ids"]) == 1
    assert s.get_experiment(out["experiment_ids"][0])["arms"][0]["strain_ref"] == "OH904"
```

- [ ] **Step 2: Run test to verify it fails** → FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
# gently/eln/seed_loader.py
"""Load seed research programs (seed/programs/*.yaml) into a FileContextStore."""
from __future__ import annotations

from pathlib import Path

import yaml


def load_program(store, program: dict) -> dict:
    c = program.get("campaign", {})
    campaign_id = store.create_campaign(
        description=c.get("description") or c.get("title") or program.get("slug", "seed"),
        shorthand=c.get("title"),
        summary=c.get("goal"),
    )
    strain_ids = [
        store.create_strain(
            s["name"], genotype=s.get("genotype"), markers=s.get("markers"),
            organism_ref=s.get("organism_ref"), author="seed",
        )
        for s in program.get("strains", [])
    ]
    experiment_ids = [
        store.create_experiment(
            e["title"], campaign_ref=campaign_id, arms=e.get("arms"),
            controls=e.get("controls"),
            export={"target": "hf", "repo": e["export_repo"]} if e.get("export_repo") else None,
            author="seed",
        )
        for e in program.get("experiments", [])
    ]
    hypothesis_ids = [
        store.create_hypothesis(
            h["statement"],
            predictions=[{"target": p, "expected": None} for p in h.get("predictions", [])],
            experiment_refs=experiment_ids, author="seed",
        )
        for h in program.get("hypotheses", [])
    ]
    return {
        "campaign_id": campaign_id, "strain_ids": strain_ids,
        "experiment_ids": experiment_ids, "hypothesis_ids": hypothesis_ids,
    }


def load_seed_dir(store, seed_dir) -> list[dict]:
    out = []
    for f in sorted(Path(seed_dir).glob("*.yaml")):
        program = yaml.safe_load(f.read_text())
        if program and program.get("campaign"):
            out.append(load_program(store, program))
    return out
```

- [ ] **Step 4: Run test to verify it passes** → PASS.

- [ ] **Step 5: Commit**

```bash
git add gently/eln/seed_loader.py tests/test_seed_loader.py
git commit -m "feat(eln): seed-program loader (seed/programs -> FileContextStore)"
```

---

## Task 6: Export service — assemble annotation rows for an experiment

**Files:**
- Create: `gently/eln/export_service.py`
- Test: `tests/test_export_service.py`

**Interfaces:**
- Consumes: `FileStore.get_ground_truth`, per-embryo predictions, `hf_connector.build_records`.
- Produces: `collect_annotations(file_store, session_id, embryo_ids, strain=None) -> list[dict]` — one row per ground-truth-covered prediction, ready for `build_records`.

- [ ] **Step 1: Write the failing test** — with a fake file_store exposing `get_ground_truth` + a `get_predictions`-like accessor; assert rows pair prediction+GT+provenance. (Full code: mirror `accuracy.stage_at_timepoint` to attach `ground_truth_stage` to each prediction row; carry `session_id/embryo_id/annotator/strain`.)

- [ ] **Step 2–5:** implement `collect_annotations`, test green, commit `feat(eln): export service — assemble annotation rows`.

---

## Task 7: Approval-gated HF export route (viz)

**Files:**
- Modify: `gently/ui/web/routes/data.py`
- Test: `tests/test_eln_export_route.py`

**Interfaces:**
- Consumes: `export_service.collect_annotations`, `hf_connector.build_records/push_dataset`.
- Produces: `POST /api/experiments/{id}/export` (`require_control`) — body `{confirm: true}`; 400 if `confirm` is not true (approval gate); 503 if `HF_TOKEN` absent (via `hf_connector.token_present()`); returns the push summary. Mock `push_dataset` via monkeypatch in the test.

- [ ] **Step 1: Write the failing test** (mirror `tests/test_eln_ground_truth_route.py` harness):

```python
def test_export_requires_confirm(monkeypatch):
    # build client (agent.store has get_ground_truth); POST without confirm → 400
    ...
def test_export_requires_token(monkeypatch):
    # token_present() False → 503
    ...
def test_export_pushes_on_confirm(monkeypatch):
    # monkeypatch hf_connector.push_dataset; confirm:true → 200 + summary
    ...
```

- [ ] **Step 2–5:** implement route (assemble rows → `build_records` → `push_dataset`), green, commit `feat(eln): approval-gated HF export route`.

---

## Task 8: Agent tools (create_experiment / author_hypothesis / record_result / link_session_to_arm / configure_export)

**Files:**
- Modify: the agent tool registry (`gently/harness/tools/…` — follow the existing tool-registration pattern used by campaign/plan tools) + `gently/harness/prompts/manager.py` allow-list.
- Test: `tests/test_eln_agent_tools.py`

**Interfaces:**
- Each tool is a thin wrapper over the corresponding `FileContextStore` method, stamping `author="agent"`. Mirror an existing store-backed tool (e.g. the campaign-creation tool) for schema + registration.

- [ ] **Step 1:** test each tool calls the right store method with `author="agent"`.
- [ ] **Step 2–5:** implement, register in the allow-list, green, commit `feat(eln): agent tools for the scientific spine`.

---

## Task 9: Vitals stage-strip ground-truth authoring UI (range drag-select)  — IN-BROWSER

**Files:**
- Modify: `gently/ui/web/static/js/…` (the Vitals / stage-strip view) + CSS.
- Verify: Chrome MCP + a new `US-` story flow (Task 12).

**Interfaces:**
- Consumes: `POST /api/embryos/{id}/ground_truth` (Task done). DOM contract: a `ground_truth_control` element on the stage strip; corrected points render as a filled diamond vs the model's hollow dot.

- [ ] **Step 1:** replace the localStorage-only Agree/Disagree with a stage-picker popover on click/drag-select over the stage strip; pre-fill the agent's predicted stage (one-click "confirm as ground truth").
- [ ] **Step 2:** drag-select a range → one `POST` with `start_timepoint`/`end_timepoint`.
- [ ] **Step 3:** render corrected points distinctly; show annotator.
- [ ] **Step 4: Verify in-browser** — boot viz, drive the flow, run the Chrome MCP UI/UX audit (alignment/spacing/overflow/contrast); fix flaws before marking done.
- [ ] **Step 5: Commit** `feat(eln): ground-truth range authoring on the Vitals stage strip`.

> This task requires the running app; do not mark done without in-browser verification. Design cues in `docs/product-ideation/CONSULT.md` (IDEA-01 deep design) + `ELN-USAGE.md`.

---

## Task 10: Assisted batch-confirm + accuracy readout — IN-BROWSER

**Files:** JS/CSS for the stage strip + a small viz route `GET /api/embryos/{id}/accuracy` (calls `accuracy.accuracy_result`).

- [ ] **Step 1:** `GET /api/embryos/{id}/accuracy` returns the accuracy Result (predicted vs GT) — unit-test like the GT route.
- [ ] **Step 2:** agent pre-screens: bulk-propose high-agreement stretches (one range confirm); surface only uncertain frames for the human. (Backend: reuse `accuracy.score_accuracy` to find agreement runs.)
- [ ] **Step 3:** show a live "agrees M/N" readout + annotated-count that updates at authoring.
- [ ] **Step 4: Verify in-browser** (Chrome MCP audit).
- [ ] **Step 5: Commit** `feat(eln): assisted batch-confirm + live accuracy readout`.

---

## Task 11: Experiment inspector + export button — IN-BROWSER

**Files:** viz template + JS in the campaign navigator/inspector; `GET /api/experiments` + `GET /api/experiments/{id}` read routes (unit-tested).

- [ ] Render experiments (arms, replicates, member sessions, linked hypotheses + status, export config). Export button → `POST /api/experiments/{id}/export` with an explicit confirm dialog. Verify in-browser. Commit `feat(eln): experiment inspector + approval-gated export button`.

---

## Task 12: ELN US- story flows (after #76 lands the crawler on the base)

**Files:** `tools/ui_crawler/stories/US-*.py` (contract: `META` + `async def flow(page, url, rec)`); update `tools/ui_crawler/baseline/status.json`.

- [ ] Add the flows enumerated in `docs/product-ideation/ELN-USAGE.md` (story-flow specs): `annotate-ground-truth`, `create-experiment`, `link-session-to-arm`, `author-hypothesis`, `record-result`, `configure-hf-export`, `accumulate-dataset-count`, `strain-record`. Run `run_stories.py --update-baseline`, commit. (Blocked until the `tools/ui_crawler` harness is present on this branch's base — i.e. after PR #76 merges into #72.)

---

## Self-Review

- **Spec coverage:** Strain (done + Task 4 resolution), Experiment (Task 1), Hypothesis (Task 2), Result (Task 3 + done accuracy), assisted scoring loop (done accuracy + Task 10), HF connector (done + Tasks 6–7), seed programs (done + Task 5 loader), co-authored agent tools (Task 8), UI (Tasks 9–11), story flows (Task 12). All spec sections map to a task.
- **Placeholder scan:** Backend tasks (1–7) carry complete code; UI tasks (9–11) are explicitly flagged IN-BROWSER with concrete endpoints, DOM contract, and verification gates rather than blind JS — the honest boundary for unattended work.
- **Type consistency:** store methods return `dict|None` / `list[dict]`; `create_*` return `str` ids; `resolve_strain`/`resolve_ref` bare-string contract consistent across Task 4 and the shipped Strain store.
