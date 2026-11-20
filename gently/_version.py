"""The single source of truth for Gently's version.

`__version__` is the part a person writes, `1.0`, and it changes when someone
decides it is 1.1. The part after it nobody writes: `build_id()` counts the
merges into `development` and reports `1.0.665`. Every merged pull request is
the next number, so two builds can be put in order by looking at them, and no
release needs a bump.

`pyproject.toml` reads `__version__` from here (`[tool.setuptools.dynamic]`),
`gently/__init__.py` re-exports it, and the web server renders `build_id()`.

This module deliberately imports nothing at the top level: setuptools reads
`__version__` by parsing the file, and falls back to *importing* it when the
parse fails. `gently/__init__.py` pulls in the whole harness, so an import
fallback there would need every runtime dependency present just to build a
wheel. A file with one literal in it can always be parsed.
"""

from __future__ import annotations

__version__ = "1.0"

_facts: tuple[str, str | None, str | None] | None = None


def _build() -> tuple[str, str | None, str | None]:
    """(build id, commit, commit date), read from git once per process: the
    code that is running is the code that was on disk when it started."""
    global _facts
    if _facts is None:
        _facts = _read_git()
    return _facts


def _read_git() -> tuple[str, str | None, str | None]:
    import subprocess
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    bare = (__version__, None, None)
    if not (repo / ".git").exists():
        return bare

    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *args], cwd=repo, capture_output=True, text=True, timeout=5, check=False
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    head = git("rev-parse", "HEAD")
    # A shallow clone has lost the history the number is counted from.
    if not head or git("rev-parse", "--is-shallow-repository") != "false":
        return bare

    # Tracked changes only: untracked screenshots and scratch files are not a
    # different build.
    dirty = git("diff", "--quiet", "HEAD") is None
    # development as a remote has it (`origin` in a direct clone, `upstream` in
    # a fork-based one), not the local branch, which can hold unmerged commits.
    refs = git("for-each-ref", "--format=%(refname)", "refs/remotes/*/development") or ""
    base, merged = head, False
    for ref in refs.split():
        chain = (git("rev-list", "--first-parent", ref) or "").split()
        if head in chain:
            merged = True
            break
        base = git("merge-base", head, ref) or base
    count = git("rev-list", "--count", "--first-parent", base)
    if not count:
        return bare

    local = "" if merged and not dirty else "+local"
    commit = head[:8] + ("-dirty" if dirty else "")
    return (f"{__version__}.{count}{local}", commit, git("log", "-1", "--format=%cI", "HEAD"))


def build_id() -> str:
    """`1.0.665`: the version and the number of merges into `development`.

    The number is `git rev-list --count --first-parent` of the commit that is
    running, so it goes up by one with each merged pull request and build 665
    is plainly older than 668. `+local` follows it when the tree is not exactly
    one of those merges: it has uncommitted edits, or it is a branch that
    `development` does not have yet (the number is then where it branched off).
    `build_commit()` says exactly which tree that is.

    Outside a full checkout (an installed wheel, a copied directory, a shallow
    clone) there is nothing to count and the bare version is the honest answer.
    """
    return _build()[0]


def build_commit() -> str | None:
    """The commit that is running, `a15d26ed`, with `-dirty` when tracked files
    have uncommitted edits. None outside a checkout."""
    return _build()[1]


def build_date() -> str | None:
    """When the commit in the build id was made — ISO 8601, with its offset.

    The build id puts builds in order; it says nothing about how old one is,
    and on a microscope the question behind "which version is this?" is
    usually "is this from before the change".

    The committer date, not the author date: a rebased or cherry-picked commit
    keeps its original author date, which would describe when the code was
    written rather than when this tree came to be.

    Returns None outside a checkout — an absent date is rendered as nothing
    rather than as a guess. Note that a `+local` build can have edits newer than
    this date; the suffix is what says so.
    """
    return _build()[2]
