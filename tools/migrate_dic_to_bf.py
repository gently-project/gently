#!/usr/bin/env python3
"""Rename the brightfield overview's old name, ``dic``, to ``bf`` on disk — by hand.

    uv run python tools/migrate_dic_to_bf.py              # dry run on the storage root
    uv run python tools/migrate_dic_to_bf.py --apply      # do it, with a backup
    uv run python tools/migrate_dic_to_bf.py --root D:/Gently3 --apply

The app does this itself at the first boot after the rename
(gently/core/migrations.py); this is the same pass with a dry run, for a
root the app is not about to open. Stop the app first: a run's checkpoint
would write the old keys straight back.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gently.core.migrations import SENTINEL, Migration  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--root", default=os.environ.get("GENTLY_STORAGE_PATH", "D:/Gently3"))
    ap.add_argument("--apply", action="store_true", help="do it (default is a dry run)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not root.is_dir():
        print(f"no such storage root: {root}", file=sys.stderr)
        return 2
    m = Migration(root, args.apply)
    m.run()
    print(m.summary())
    if args.apply:
        (root / SENTINEL).write_text("by hand\n", encoding="utf-8")
        print(f"backup of rewritten files: {m.backup}\nlog: {m.log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
