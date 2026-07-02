"""Load the shipped seed research programs into a gently store.

Loads ``seed/programs/*.yaml`` as real Campaign/Strain/Experiment/Hypothesis records
into ``{storage}/agent`` (the FileContextStore) so a fresh gently boots with real
notebook content instead of stubs.

Usage:
    python scripts/load_seed_programs.py                 # into the default storage
    python scripts/load_seed_programs.py --storage /path # into a specific store
"""

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

from gently.eln.seed_loader import load_seed_dir  # noqa: E402
from gently.harness.memory.file_store import FileContextStore  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="Load seed research programs into a gently store")
    ap.add_argument("--storage", default=None, help="Storage base path (default: settings)")
    args = ap.parse_args()

    if args.storage:
        base = Path(args.storage)
    else:
        from gently.settings import settings
        base = settings.storage.base_path

    agent_dir = base / "agent"
    store = FileContextStore(agent_dir)
    loaded = load_seed_dir(store, _REPO / "seed" / "programs")
    print(f"Loaded {len(loaded)} seed programs into {agent_dir}")
    for rec in loaded:
        camp = store.get_campaign(rec["campaign_id"])
        title = ""
        if camp is not None:
            title = (getattr(camp, "shorthand", None) or getattr(camp, "description", "") or "")[:60]
        print(
            f"  {rec['campaign_id']}  {title}  "
            f"({len(rec['strain_ids'])} strains, {len(rec['experiment_ids'])} experiments, "
            f"{len(rec['hypothesis_ids'])} hypotheses)"
        )


if __name__ == "__main__":
    main()
