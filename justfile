# The commands this repo is developed with. `just` lists them.
#
#   uv tool install rust-just      # once; puts `just` on PATH (Windows too)
#
# Every recipe runs with `uv run --no-sync`: a plain `uv run` re-syncs the
# environment first, which on the microscope computer uninstalls the torch-gpu
# and sam extras. So run `just sync` (or `just sync-rig`) once before the rest.
#
# Nothing here reads or writes the rig's data: every recipe gets the storage
# root below, whatever GENTLY_STORAGE_PATH is in the calling shell.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]

export GENTLY_STORAGE_PATH := env("GENTLY_DEV_STORAGE", home_directory() / ".gently-dev")
run := "uv run --no-sync"

_default:
    @just --list --unsorted

# Install the environment for a machine with no microscope.
sync:
    uv sync

# Install the environment on the microscope computer: a bare `uv sync` there removes torch and SAM.
sync-rig:
    uv sync --extra torch-gpu --extra sam

# The UI on http://localhost:8080 with no hardware, no API key and no login.
[group('app')]
dev *args:
    {{ run }} python launch_gently.py --offline --no-api --no-auth --no-browser {{ args }}

# A session with embryos, projections and predictions in the dev storage, so the UI has content.
[group('app')]
seed *args:
    {{ run }} python tools/seed_demo_session.py {{ args }}

# Two projects with sessions, a plan and references in the dev storage.
[group('app')]
seed-projects *args:
    {{ run }} python tools/seed_project_layer.py {{ args }}

# The simulated rig: the real device layer on 127.0.0.1:60610, three embryos in the dish.
[group('app')]
sim *args:
    {{ run }} python tools/sim_rig.py --storage "{{ GENTLY_STORAGE_PATH }}" {{ args }}

# The app against the simulated rig. Start `just sim` first, in another terminal.
[group('app')]
sim-app *args:
    {{ run }} python launch_gently.py --no-api --no-auth --no-browser {{ args }}

# The Python suite on every core, about a minute. `just test tests/test_x.py -k name` narrows it.
[group('check')]
test *args="-n auto":
    {{ run }} pytest -q {{ args }}

# The JavaScript unit tests (Node 21 or later).
[group('check')]
test-js:
    node --test "tests/js/*.test.mjs"

# Everything that gates a pull request except the suites: ruff, and mypy both ways.
[group('check')]
lint:
    {{ run }} pre-commit run --all-files
    {{ run }} mypy .

# What a pull request is checked for, in the order that fails fastest.
[group('check')]
check: lint test-js test

# Name the build that is running as a release: tag v<build> on GitHub, notes from the pull requests since the last one.
[group('release')]
release build=`uv run --no-sync python -c "from gently._version import build_id; print(build_id())"` commit=`git rev-parse HEAD`:
    {{ if build =~ '^\d+\.\d+\.\d+$' { "" } else { error("build " + build + " is not a merge on development: check out development, pull, and have no uncommitted edits") } }}
    gh release create "v{{ build }}" --repo gently-project/gently --target {{ commit }} --title "gently {{ build }}" --generate-notes
