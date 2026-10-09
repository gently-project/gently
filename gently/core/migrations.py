"""On-disk migrations for the file store, run once, at boot, before anything
reads the store.

There is one so far. The brightfield overview channel used to be called
``dic`` everywhere — in snapshot names, frame metadata, the plan and the
checkpoint a session keeps, and the agent's plans. The code was renamed to
``bf`` with no read-side shim, so what a session already holds is renamed
to match (``migrate_dic_to_bf``). ``tools/migrate_dic_to_bf.py`` is the
same thing by hand, with a dry run.

What that migration touches, and only this:

  sessions/*/snapshots/dic_<stem>.tif         -> bf_<stem>.tif
  sessions/*/snapshots/dic_<stem>.meta.yaml   -> bf_<stem>.meta.yaml, with
                                                 source/channel/file_path rewritten
  sessions/*/{acquisition,timelapse,summary,intent}.yaml   keys dic* -> bf*
  sessions/*/timeline.jsonl                   event payload keys "dic" -> "bf"
  agent/**/*.yaml|json                        plan/tactic structures' dic -> bf

The rewrite is the token rule the code rename used: ``dic`` where it is not
part of another word (``dict``, ``indicator`` and ``periodic`` are left
alone). Conversation and interaction logs are history and are not touched.

Every file rewritten is first copied under ``<root>/_migration_backup/`` at
its relative path, and every rename and rewrite is appended to
``<root>/migrate_dic_to_bf.log.jsonl``, so the whole thing can be undone by
hand. Re-running is safe: a file that no longer says ``dic`` is skipped. At
boot a sentinel, ``<root>/.migrated_dic_to_bf``, says it has been done, so
the store is not walked on every start.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN = re.compile(r"(?<![A-Za-z])dic(?![a-z])")
SESSION_FILES = (
    "acquisition.yaml",
    "timelapse.yaml",
    "summary.yaml",
    "intent.yaml",
    "timeline.jsonl",
)
SENTINEL = ".migrated_dic_to_bf"
LOG_NAME = "migrate_dic_to_bf.log.jsonl"
BACKUP_DIR = "_migration_backup"


def rewrite_text(text: str) -> tuple[str, int]:
    """The text with every ``dic`` token renamed, and how many lines changed."""
    out, n = [], 0
    for line in text.split("\n"):
        new = TOKEN.sub("bf", line)
        if new != line:
            n += 1
        out.append(new)
    return "\n".join(out), n


class Migration:
    """One pass over a storage root. ``apply=False`` only counts."""

    def __init__(self, root: Path, apply: bool) -> None:
        self.root = Path(root)
        self.apply = apply
        self.backup = self.root / BACKUP_DIR
        self.log_path = self.root / LOG_NAME
        self.renamed = 0
        self.rewritten = 0
        self.lines = 0
        self.skipped = 0

    def log(self, **rec: object) -> None:
        if not self.apply:
            return
        rec["at"] = datetime.now().isoformat(timespec="seconds")
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec) + "\n")

    def _backup(self, path: Path) -> None:
        dest = self.backup / path.relative_to(self.root)
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)

    def rewrite(self, path: Path) -> None:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            self.skipped += 1
            return
        if "dic" not in text:
            return
        new, n = rewrite_text(text)
        if not n:
            return
        self.rewritten += 1
        self.lines += n
        if self.apply:
            self._backup(path)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(new, encoding="utf-8", newline="")
            os.replace(tmp, path)
            self.log(op="rewrite", path=str(path), lines=n)

    def rename(self, path: Path) -> None:
        new = path.with_name("bf" + path.name[3:])
        self.renamed += 1
        if self.apply:
            if new.exists():
                raise FileExistsError(f"{new} already exists; refusing to overwrite")
            os.replace(path, new)
            self.log(op="rename", old=str(path), new=str(new))

    def session(self, sd: Path) -> None:
        snaps = sd / "snapshots"
        if snaps.is_dir():
            for p in sorted(snaps.iterdir()):
                if not p.name.startswith("dic_"):
                    continue
                if p.name.endswith(".meta.yaml"):
                    self.rewrite(p)
                self.rename(p)
        for name in SESSION_FILES:
            p = sd / name
            if p.is_file():
                self.rewrite(p)

    def run(self) -> None:
        sessions = self.root / "sessions"
        if sessions.is_dir():
            for sd in sorted(sessions.iterdir()):
                if sd.is_dir() and not sd.name.startswith("_"):
                    self.session(sd)
        agent = self.root / "agent"
        if agent.is_dir():
            for p in sorted(agent.rglob("*")):
                if p.is_file() and p.suffix in (".yaml", ".yml", ".json", ".jsonl"):
                    self.rewrite(p)

    def summary(self) -> str:
        mode = "applied" if self.apply else "dry run"
        return (
            f"dic-to-bf {mode} on {self.root}: {self.renamed} files renamed, "
            f"{self.rewritten} files rewritten ({self.lines} lines), "
            f"{self.skipped} unreadable skipped"
        )


def migrate_dic_to_bf(root: Path, force: bool = False) -> Migration | None:
    """Run the migration once for this root, at boot. None when already done.

    Nothing must be running against the store: the checkpoint a live run
    writes would put the old keys straight back. The sentinel is written only
    after a complete pass, so an interrupted one runs again next boot.
    """
    root = Path(root)
    sentinel = root / SENTINEL
    if sentinel.exists() and not force:
        return None
    m = Migration(root, apply=True)
    m.run()
    if m.renamed or m.rewritten:
        logger.info(m.summary())
    sentinel.write_text(datetime.now().isoformat(timespec="seconds") + "\n", encoding="utf-8")
    return m
