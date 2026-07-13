"""Load seed research programs (``seed/programs/*.yaml``) into a FileContextStore.

Each program is imported as a Campaign + Strain(s) + Experiment(s) + Hypothesis(es).
Idempotency is the caller's concern — loading twice creates duplicates.
"""

from __future__ import annotations

from pathlib import Path

import yaml


def load_program(store, program: dict) -> dict:
    """Import one seed program dict; return the created entity ids."""
    c = program.get("campaign", {})
    campaign_id = store.create_campaign(
        description=c.get("description") or c.get("title") or program.get("slug", "seed"),
        shorthand=c.get("title"),
        summary=c.get("goal"),
    )
    strain_ids = [
        store.create_strain(
            s["name"],
            genotype=s.get("genotype"),
            markers=s.get("markers"),
            organism_ref=s.get("organism_ref"),
            author="seed",
        )
        for s in program.get("strains", [])
    ]
    experiment_ids = [
        store.create_experiment(
            e["title"],
            campaign_ref=campaign_id,
            arms=e.get("arms"),
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
            experiment_refs=experiment_ids,
            author="seed",
        )
        for h in program.get("hypotheses", [])
    ]
    return {
        "campaign_id": campaign_id,
        "strain_ids": strain_ids,
        "experiment_ids": experiment_ids,
        "hypothesis_ids": hypothesis_ids,
    }


def load_seed_dir(store, seed_dir) -> list[dict]:
    """Load every ``*.yaml`` program under ``seed_dir``. Returns per-program ids."""
    out = []
    for f in sorted(Path(seed_dir).glob("*.yaml")):
        program = yaml.safe_load(f.read_text())
        if program and program.get("campaign"):
            out.append(load_program(store, program))
    return out
