# Contributing to Gently

## Code quality toolchain

This project uses [ruff](https://docs.astral.sh/ruff/) for linting and formatting, and
[mypy](https://mypy-lang.org/) for type checking, enforced automatically before every
commit via [pre-commit](https://pre-commit.com/).

### First-time setup

Install the dev dependencies (includes ruff, mypy, and pre-commit):

```bash
uv sync
```

Then install the pre-commit hooks:

```bash
pre-commit install
```

From this point on, ruff runs on staged files and mypy runs across the whole
project whenever you `git commit`.

### Running manually

`just check` runs everything below and the two test suites (see the `justfile`;
`uv tool install rust-just` once).

To check all files at once (useful before opening a PR):

```bash
pre-commit run --all-files
```

Or run the tools directly:

```bash
ruff check .          # lint
ruff format .         # format in-place
```

### Keeping hooks up to date

To update hook versions to their latest releases:

```bash
pre-commit autoupdate
```

### Type checking

mypy runs two ways, and they can disagree:

- `mypy .` — no project dependencies installed. `[tool.mypy]` sets
  `ignore_missing_imports = true`, so third-party imports fall back to `Any`.
  This is the form the pre-commit hook runs.
- `uv run mypy .` — after `uv sync`, with the real packages present, so mypy
  checks their actual types and can surface mismatches the deps-less run cannot.

A green run of one says nothing about the other, so run `uv run mypy .` before
pushing if you touched code that uses a typed third-party library. New code must
type-clean under both.

### CI

`.github/workflows/lint.yml` is the source of truth for what gates a pull
request, and it changes — read it rather than trusting a summary here.
`pre-commit run --all-files` reproduces the ruff checks and the deps-less
`mypy .` locally, but **not** the deps-installed run; reproduce that with
`uv run mypy .` after `uv sync`.

The test suite gates a pull request too, on Linux and on Windows:
`uv run pytest -n auto` (every core; about a minute) and the JavaScript unit
tests (`node --test tests/js/<file>.test.mjs`, one file at a time). Run both
before pushing. CI reads its Python version from `.python-version`, the same
file `uv sync` reads, so the two cannot differ. The suite is expected to be fully green; a test that fails
only when run with the others is a bug in the tests, not a known failure.

## Versions and releases

Feedback is only actionable if it names a build. Keep that true.

### The number

`1.0.665`: the version, and the number of merges into `development`.

- **`1.0`** is `__version__` in `gently/_version.py`, the one place a person
  writes it. Change it, through a pull request, when it is 1.1 or 2.0.
  `pyproject.toml` derives it via `[tool.setuptools.dynamic]`;
  `tests/test_version_is_single_sourced.py` fails if a second copy appears.
- **`665`** nobody writes. `build_id()` counts the first-parent commits of
  `development` up to the one that is running, so each merged pull request is
  the next number and 665 is plainly older than 668. There is nothing to bump.
- **`+local`** follows the number when the tree is not exactly one of those
  merges: uncommitted edits to tracked files, or a branch `development` does
  not have yet (the number is then where it branched off).

It appears on the launch gate footer (hover for the commit), on the Settings
page with the commit and its date, at `/openapi.json`, and in every
`session.yaml` as `gently_build` and `gently_commit`, so a session says what
code acquired it.

**Ask for the number from the launch gate in every bug report.** A report that
says `+local` did not come from a build anyone else has.

The count needs the history: a wheel, a copied folder or a shallow clone shows
the bare `1.0`. The microscope computers run from a full clone and `git pull`.

### Releases

A release is a new minor version: 1.0 becoming 1.1. Builds in between have
their number and nothing else; there are several a day, and a release of each
would bury the ones that mean something.

To release, change `__version__` in `gently/_version.py` in a pull request and
merge it. `.github/workflows/release.yml` then tags that merge `v1.1` and
creates the GitHub release, its notes the pull requests merged since the last
one. There is no other step, and nothing to run by hand.

The count does not start again: the build after `1.0.700` is `1.1.701`, so
build numbers stay in order across releases.
