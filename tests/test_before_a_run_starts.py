"""What stands in the way of a run is said before Start, where the press is.

The owner, on the drawing of it: "i love the before it starts idea... really
good."

The page knew, and did not say. With three embryos registered and none
calibrated the plan's sentence read "SPIM volumes of 3 embryos" with nothing
under it, and the press answered "Start failed (409 — not calibrated:
embryo_2 … or pass allow_uncalibrated=true to acquire anyway...)". Start
itself followed the form and sat 107 px under the fold of a maximized window.
And nothing said what a run would write: the form opens at every 30 s for
16 h, about 576 GB for three embryos.

The sentences are pinned in tests/js/run-preflight.test.mjs. CI drives no
browser, so what is pinned here is that the page asks, draws them between the
sentence and Start, counts the ones in the way onto Start, and keeps Start in
a foot that does not scroll.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core.file_store import FileStore
from gently.ui.web import auth
from gently.ui.web.routes.data import create_router

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
PREFLIGHT = (WEB / "static" / "js" / "run-preflight.js").read_text(encoding="utf-8")
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")


def _fn(src: str, head: str) -> str:
    """The body of a function, from its head to the next one at its depth."""
    start = src.index(head)
    indent = re.match(r"\s*", head).group(0)  # type: ignore[union-attr]
    nxt = re.search(rf"\n{indent}(?:async )?function |\n{indent}// ══", src[start + len(head) :])
    return src[start : start + len(head) + (nxt.start() if nxt else len(src))]


def _app(store=None, server_store=None):
    server = MagicMock()
    server.agent_bridge.agent.store = store
    server.gently_store = server_store
    app = FastAPI()
    app.include_router(create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


# ── the one thing asked of the server: the disk's free room ──────────────


def test_the_room_route_says_what_the_disk_has_free(tmp_path):
    store = FileStore(root=tmp_path)
    r = _app(store=store).get("/api/devices/timelapse/room")
    assert r.status_code == 200
    body = r.json()
    assert body["free_bytes"] > 0 and body["total_bytes"] >= body["free_bytes"]
    assert Path(body["path"]) == tmp_path


def test_the_room_route_reads_the_same_disk_before_a_session_is_live(tmp_path):
    # At the launch gate the agent has no store; the server's own is the
    # same disk, and the line is worth having as soon as the pane is open.
    r = _app(store=None, server_store=FileStore(root=tmp_path)).get("/api/devices/timelapse/room")
    assert r.status_code == 200 and r.json()["free_bytes"] > 0


def test_the_room_route_never_errors_when_the_disk_cannot_be_read():
    # An unread disk is a line left out, not a pane that will not draw.
    r = _app(store=None, server_store=None).get("/api/devices/timelapse/room")
    assert r.status_code == 200
    assert r.json() == {"free_bytes": None, "total_bytes": None, "path": None}


# ── the page asks, and draws the lines between the sentence and Start ─────


def test_the_module_is_loaded_before_the_page_that_uses_it():
    plan = HTML.index('src="/static/js/acquisition-plan.js"')
    pre = HTML.index('src="/static/js/run-preflight.js"')
    page = HTML.index('src="/static/js/operate.js"')
    assert plan < pre < page


def test_the_lines_sit_between_the_sentence_and_start():
    say = HTML.index('id="op-plan-say"')
    lines = HTML.index('id="op-preflight"')
    start = HTML.index('id="op-run-start"')
    assert say < lines < start
    # A list, named, that Start is described by.
    host = HTML[lines - 80 : lines + 160]
    assert 'role="list"' in host and 'aria-label="Before it starts"' in host
    assert 'aria-describedby="op-preflight"' in HTML[start - 120 : start + 120]


def test_start_is_in_a_foot_that_does_not_scroll():
    # The run's column: the sentence, the lines, then Start in its foot. The
    # column does not scroll; the plan's beside it may, and the lines scroll
    # inside their own box if there are more than fit.
    run = HTML.index('class="op-acq-col op-acq-run"')
    foot = HTML.index('class="op-runfoot"')
    assert run < HTML.index('id="op-plan-say"') < HTML.index('id="op-preflight"') < foot
    assert foot < HTML.index('id="op-run-start"')

    def rule(sel):
        body = CSS[CSS.index(sel) :]
        return body[: body.index("}")]

    assert "overflow-y: auto" in rule(".op-acq-plan {")
    assert "overflow" not in rule(".op-acq-col {")
    assert "flex: 1 1 auto" in rule(".op-acq-run > .op-acq-pf {")
    assert "overflow-y: auto" in rule(".op-preflight {")
    foot_rule = rule(".op-runfoot {")
    assert "margin-top: auto" in foot_rule


def test_the_lines_are_derived_from_what_the_page_has_read():
    ctx = _fn(OPERATE, "    function preflightContext(plan) {")
    for needed in (
        "hasFit(e)",  # the field the server's gate checks
        "AcquisitionPlan.validate(plan,",  # what Start used to toast
        "LightPanel.wavelengthsOf(light.config)",  # the lines the rig routes now
        "fd.pos()",  # where the head is
        "_room.free_bytes",  # the disk
        "BrightfieldRefs.status()",  # the overview's dark and flat
        "RunPreflight.estimate(plan,",
    ):
        assert needed in ctx, needed
    # An unread preset is not a dark one.
    assert "light.config &&" in ctx


def test_the_room_is_read_when_the_pane_opens():
    assert "restorePlan(); readRoom(); renderRun();" in OPERATE
    read = _fn(OPERATE, "    async function readRoom() {")
    assert "getJSON('/api/devices/timelapse/room')" in read


def test_what_is_in_the_way_is_counted_onto_start():
    btn = _fn(OPERATE, "    function renderRunButton() {")
    assert "RunPreflight.verdict(_preflight)" in btn
    assert "b.disabled = _runBusy || v.blocked > 0;" in btn
    assert "v.says || RUN_VERB[_mode]" in btn
    # Wearing the verdict is not looking like a button that failed to load.
    assert ".op-btn-primary.is-blocked" in CSS


def test_the_plan_redraws_the_lines_and_so_do_the_light_and_the_head():
    assert "renderPreflight(plan);" in _fn(OPERATE, "    function renderPlan() {")
    redraw = "if (_pane === 'acquire') renderPreflight();"
    assert f"SharedState.on('light', () => {{ {redraw} }});" in OPERATE
    assert f"onRead: () => {{ renderGoto(); {redraw} }}," in OPERATE


def test_each_fix_is_one_press():
    fix = _fn(OPERATE, "    function preflightFix(action) {")
    for action in ("'calibrate'", "'without'", "'head'", "'overview'"):
        assert f"action === {action}" in fix, action
    # Running without them is the "Selected" scope, the mechanism the pane
    # already has and already keeps with the plan: not a second one.
    assert "setTargetScope('selected');" in fix
    # Pointing the instrument at the embryo to calibrate must not narrow the
    # set a run images.
    assert "_targets.includes(first.id)" in fix
    assert "data-preflight-fix" in OPERATE and "preflightFix(b.dataset.preflightFix)" in OPERATE


def test_a_line_says_what_kind_it_is_in_words_as_well_as_by_its_mark():
    draw = _fn(OPERATE, "    function renderPreflight(plan) {")
    assert 'aria-hidden="true"' in draw and "PREFLIGHT_SAID[l.kind]" in draw
    assert "In the way: " in OPERATE


def test_a_line_that_says_what_it_said_is_not_redrawn():
    # Typing a cadence and then pressing a fix blurs the field, which re-says
    # the plan. A list replaced whole between the press and the release
    # swallows the press: in the browser the button did nothing, every time,
    # when it was the first thing pressed after typing.
    draw = _fn(OPERATE, "    function renderPreflight(plan) {")
    assert "patchLines(host, _preflight.map(" in draw
    assert "host.innerHTML" not in draw
    patch = _fn(OPERATE, "    function patchLines(host, html, opts) {")
    assert "if (had[i] === h && host.children[i]) return;" in patch


def test_the_acquisition_roster_shows_the_fit():
    mount = OPERATE[OPERATE.index("RosterPanel.mount('op-roster',") :][:200]
    assert "showFit: true" in mount


def test_the_cadence_kept_is_said_beside_the_cadence_asked():
    assert 'id="op-plan-kept"' in HTML
    assert HTML.index('id="op-plan-unit"') < HTML.index('id="op-plan-kept"')
    assert "RunPreflight.keptWords(ctx.est)" in OPERATE


def test_the_cost_of_an_embryo_says_where_its_number_came_from():
    # A constant in a page script is a claim about a rig. It names its
    # measurement, and says when to stop trusting it.
    at = PREFLIGHT.index("const OVERHEAD_S")
    head = PREFLIGHT[at - 500 : at]
    assert "6,919" in head and "shortcut:" in head
