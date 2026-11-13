"""Acquisition is one surface with two states, in Scope's three zones.

The owner, on the drawing of it (docs/workspace/mockup-run-v1.html): "agreed
with the mockup, you can make them."

Designing a run and watching one never happen at the same time, and the pane
drew both always: three columns, of which the right third said "Nothing
running" before a run and the middle was a form for a run already started
during one. Start followed the form and sat under the fold. What is per
embryo was in three places, and a test volume ended in a toast with its
picture shown nowhere on the page that took it.

Now: the dish as a table (left), each embryo's latest volume (middle), the
plan and the run (right); `data-acq` on the pane says which state, and
`data-when` on a part says which state it belongs to.

CI drives no browser, so the structure is pinned here. What it looks like and
does was checked on the simulated rig at 1920x889 and 1440x920
(docs/workspace/calibration-and-acquisition.md).
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
ROSTER = (WEB / "static" / "js" / "panels" / "roster.js").read_text(encoding="utf-8")
HTML = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")

PANE = HTML[HTML.index('id="op-pane-acquire"') :]
PANE = PANE[: PANE.index("</section>\n\n                  </div><!-- .op-panearea -->")]


def _fn(src: str, head: str) -> str:
    """A function's body, from its head to the next thing at its depth."""
    start = src.index(head)
    indent = re.match(r"\s*", head).group(0)  # type: ignore[union-attr]
    rest = src[start + len(head) :]
    nxt = re.search(
        rf"\n{indent}(?:async )?function |\n{indent}// ══|\n{indent}let |\n{indent}const ", rest
    )
    return src[start : start + len(head) + (nxt.start() if nxt else len(rest))]


def _rule(selector: str) -> str:
    body = CSS[CSS.index(selector) :]
    return body[: body.index("}")]


# ── one surface, two states ──────────────────────────────────────────────


def test_the_pane_says_which_state_it_is_in_and_each_part_which_it_belongs_to():
    assert 'data-acq="design"' in HTML[HTML.index('id="op-pane-acquire"') - 80 :][:260]
    whens = set(re.findall(r'data-when="(\w+)"', PANE))
    assert whens == {"design", "watch"}
    hide = '.op-pane-acquire[data-acq="design"] [data-when="watch"],'
    assert hide in CSS
    assert '.op-pane-acquire[data-acq="watch"] [data-when="design"] { display: none; }' in CSS


def test_the_three_zones_are_the_dish_a_picture_and_the_controls():
    order = [
        PANE.index(c) for c in ('class="op-acq-dish"', 'class="op-acq-view"', 'class="op-acq-side"')
    ]
    assert order == sorted(order)
    grid = _rule(".op-acq {")
    assert "grid-template-columns: 300px minmax(0, 1fr) auto;" in grid
    # The old three always-there columns are gone.
    assert "op-main-cols" not in PANE and 'id="op-modes"' not in PANE


def test_what_belongs_to_which_state():
    def when(marker: str) -> str | None:
        tag = PANE[PANE.rindex("<", 0, PANE.index(marker)) :]
        tag = tag[: tag.index(">")]
        m = re.search(r'data-when="(\w+)"', tag)
        return m.group(1) if m else None

    # Designing: the form, the lines, Start.
    for marker in (
        'id="op-panel-adaptive"',
        'id="op-roster"',
        'id="op-test-one"',
        'class="op-runfoot"',
    ):
        assert when(marker) == "design", marker
    # Watching: the run's rows, its clock, the plan as started.
    for marker in ('id="op-runspine"', 'class="op-panel op-acq-clock"', 'id="op-run-tactics"'):
        assert when(marker) == "watch", marker
    # Both: the pictures.
    assert when('id="op-tiles"') is None


def test_the_state_follows_the_run():
    run = _fn(OPERATE, "    async function renderRun() {")
    # Going: running, a live tactic, or interrupted. A run somebody stopped
    # is one they are done with, so the form is back.
    assert (
        "const going = !!running || live.length > 0 || (resumable && st.ended !== 'stopped');"
        in run
    )
    assert (
        "if (going !== _runGoing) { _runGoing = going; setAcqView(going ? 'watch' : 'design'); }"
        in run
    )
    # Only the change moves it: the operator's own choice is left alone.
    view = _fn(OPERATE, "    function setAcqView(view) {")
    assert "pane.dataset.acq = _acqView;" in view
    # Start lands on the run.
    assert "setAcqView('watch');" in _fn(OPERATE, "    function landOnRun(sentence) {")


def test_with_no_run_going_the_operator_may_look_back_or_plan_another():
    assert "fresh.addEventListener('click', () => setAcqView('design'))" in OPERATE
    assert "lastRun.addEventListener('click', () => setAcqView('watch'))" in OPERATE
    run = _fn(OPERATE, "    async function renderRun() {")
    assert "back.hidden = going || !anything;" in run
    assert "if (fresh) fresh.hidden = !!running;" in run


# ── the dish, as a table ─────────────────────────────────────────────────


def test_the_roster_is_a_table_of_what_is_per_embryo():
    mount = OPERATE[OPERATE.index("RosterPanel.mount('op-roster', {") :][:320]
    for said in (
        "table: true",
        "showFit: true",
        "cell: emb => endingCell(emb)",
        "out: emb => !inRun(emb)",
    ):
        assert said in mount, said
    head = PANE[PANE.index('class="op-acq-thead"') :][:200]
    assert "<span>#</span><span>role</span><span>fit</span><span>ends</span>" in head
    row = _fn(ROSTER, "    function tableRow(emb, selected, inSet, opts) {")
    assert 'data-verb="toggleRole"' in row and "fitCell(emb)" in row and "opts.cell(emb)" in row


def test_the_fit_is_said_as_numbers():
    cell = _fn(ROSTER, "    function fitCell(emb) {")
    assert "slope.toFixed(1)" in cell and "r2.toFixed(2)" in cell
    # The worse of the two ends, as everywhere a fit is judged.
    assert "Math.min(...ends)" in cell
    # Whose slope, when it was borrowed.
    assert "cal.borrowed_from" in cell and "`from ${from}`" in cell
    assert "uncal" in cell


def test_an_embryos_own_ending_is_a_cell_on_its_row():
    cell = _fn(OPERATE, "    function endingCell(emb) {")
    assert "stopOptions(c.kind, true)" in cell
    assert 'data-ending="kind"' in cell and 'data-ending="value"' in cell
    assert "aria-label=" in cell
    # A reference is not imaged, so it has no ending.
    assert "emb.role === 'calibration'" in cell
    read = _fn(OPERATE, "    function readPlan() {")
    assert "Object.keys(_endings).filter(id => inRun.has(id))" in read
    assert (
        "roster.cellChange" in OPERATE
        or "cellChange: (id, control) => setEnding(id, control)," in OPERATE
    )
    assert "v.cellChange(row.dataset.embryo, e.target)" in ROSTER


def test_a_control_in_a_cell_is_used_not_taken_for_a_click_on_the_row():
    wire = _fn(ROSTER, "    function wire(host, opts) {")
    # A plain click on a row replaces the selection: that must never be how
    # an ending gets chosen.
    assert "if (e.target.closest('[data-cell]')) return;" in wire
    assert "if (e.target.closest('[data-cell], [data-verb]')) return;" in wire


def test_a_row_being_typed_in_is_not_redrawn_under_the_hand():
    # Found in the browser: a redrawn row took the focus with it, and the
    # next digits typed went to the page, where a digit is a tab shortcut.
    patch = _fn(ROSTER, "    function patch(host, parts) {")
    assert "if (had[i] === html && host.children[i]) return;" in patch
    assert "host.children[i].contains(held)" in patch
    assert "host.innerHTML" not in _fn(ROSTER, "    function render() {")
    # And it is caught up when the focus leaves.
    assert "host.addEventListener('focusout'" in ROSTER


def test_a_number_box_has_no_spinner_to_land_on():
    # A press meant to put the cursor in a 40 px box landed on the arrow and
    # changed the number instead.
    assert '.op-numbox[type="number"]::-webkit-inner-spin-button' in CSS
    assert "appearance: textfield" in _rule('.op-numbox[type="number"] {')


def test_the_same_table_has_the_runs_columns_while_it_runs():
    head = PANE[PANE.index('class="op-acq-thead op-acq-thead-run"') :][:220]
    assert "<span>#</span><span>t</span><span>next</span><span>ends</span>" in head
    row = _fn(OPERATE, "    function runRow(id, r, live) {")
    assert "data-run-stop=" in row and "data-run-halt=" in row
    # What its next acquisition uses, which the agent changes per embryo.
    assert "paramsWords(r)" in row
    run = _fn(OPERATE, "    async function renderRun() {")
    # A row whose ending is being chosen is not redrawn by the next poll.
    assert "{ keepFocused: true });" in run


# ── the pictures ─────────────────────────────────────────────────────────


def test_a_tile_is_the_embryos_saved_projection():
    model = _fn(OPERATE, "    function tilesModel() {")
    # The JPEG the store already wrote, served as a file. Not the route that
    # loads the whole volume and projects it on every request.
    assert "/projection?embryo=" in model and "&t=${t}" in model
    assert "/api/projections/" not in model
    draw = _fn(OPERATE, "    function renderTiles() {")
    assert 'loading="lazy"' in draw and "alt=" in draw
    assert "patchLines(host," in draw


def test_the_tiles_are_as_large_as_the_room_allows():
    fit = _fn(OPERATE, "    function fitTiles() {")
    # The box, not what is left beside a scrollbar: that went round in a
    # circle and ended with a scrollbar and nothing to scroll.
    assert "host.offsetWidth" in fit and "host.offsetHeight" in fit
    assert "host.style.overflowY = 'hidden';" in fit
    assert "new ResizeObserver(() => fitTiles()).observe(tiles)" in OPERATE
    assert "aspect-ratio: 1024 / 630;" in _rule(".op-tile {")


def test_a_tile_pressed_points_the_instrument_and_leaves_the_run_alone():
    point = _fn(OPERATE, "    function pointAt(id) {")
    assert "if (_targets.includes(id)) {" in point
    assert "_selected = id;" in point
    # Not selectEmbryo for a member: a plain select would narrow the set.
    assert point.index("_selected = id;") < point.index("selectEmbryo(id);")


def test_a_brightfield_run_shows_the_overviews_frames():
    assert "getJSON('/api/bf/frames')" in _fn(OPERATE, "    async function readOverviewFrames() {")
    kind = _fn(OPERATE, "    function picturesKind() {")
    assert "!volumes ? 'overview' : !overview ? 'volumes' : _tilesKind" in kind
    # The choice is drawn only when there are both.
    assert "kindSeg.hidden = !(pics.volumes && pics.overview);" in _fn(
        OPERATE, "    function renderTiles() {"
    )
    assert 'id="op-tiles-kind"' in PANE


# ── a test volume ────────────────────────────────────────────────────────


def test_a_test_volume_is_a_button_beside_the_pictures():
    view = PANE[PANE.index('class="op-acq-viewbar"') : PANE.index('id="op-tiles"')]
    assert 'id="op-test-one"' in view
    take = _fn(OPERATE, "    async function testVolume() {")
    # With the plan's own slices and exposure: it had fields of its own.
    assert "plan.spim.slices != null ? plan.spim.slices" in take
    assert "plan.spim.exposureMs != null ? plan.spim.exposureMs" in take
    assert 'id="op-vol-slices"' not in HTML
    # Its picture, on its tile, now.
    assert "onEmbryosUpdate(await getJSON('/api/embryos/current'))" in take


def test_a_test_volume_says_why_it_cannot_before_it_is_pressed():
    name = _fn(OPERATE, "    function renderSingle() {")
    assert "has no calibration: a volume of it would be refused" in name
    assert "b.disabled = !!why;" in name


def test_a_refused_volume_is_said_in_the_operators_words():
    take = _fn(OPERATE, "    async function testVolume() {")
    assert "e.status === 409 && /not calibrated/i" in take
    assert "has no calibration.`" in take
    assert "allow_uncalibrated" not in take.replace("allow_uncalibrated=true to acquire", "")


# ── the plan ─────────────────────────────────────────────────────────────


def test_the_plan_is_boxes_whose_labels_are_beside_their_values():
    plan = PANE[PANE.index('id="op-panel-adaptive"') : PANE.index('class="op-acq-col op-acq-run"')]
    names = re.findall(
        r'<h3 class="op-panel-name">(?:<label[^>]*>.*?</label>|([A-Za-z ]+))', plan, re.S
    )
    assert [n for n in names if n] == ["Cadence", "Ends", "Watching"]
    assert 'id="op-plan-spim"' in plan and 'id="op-plan-bf"' in plan
    # Nothing in it grows with the roster.
    assert "op-plan-overrides" not in plan
    assert "flex: 0 0 54px" in _rule(".op-acq-plan .op-label {")


def test_a_label_does_not_uppercase_a_unit():
    # "405 nm" came out "405 NM", and N·M is a torque.
    rows = _fn(OPERATE, "    function renderPowerRows() {")
    assert 'title="The ${wl} nm line">${wl}</label>' in rows
    assert "${wl} nm</label>" not in rows


def test_a_saved_plan_fills_the_form_and_a_tactic_runs_as_it_is():
    choose = _fn(OPERATE, "    function chooseSaved(id) {")
    assert "fillPlan(AcquisitionPlan.fromStructure(t.structure));" in choose
    assert "setMode('library');" in choose
    # A loaded plan is a pending change: the embryos do not hold it yet, and
    # a form that follows the embryos would write theirs back over it.
    assert "_planDirty = true;" in choose
    start = _fn(OPERATE, "    async function startRun() {")
    # Left as loaded, it is run as that tactic, so the run is filed as it.
    assert "if (_loaded && !_loaded.edited && !(_setupItem && _setupItem.id)) {" in start
    assert "if (_loaded) _loaded.edited = true;" in _fn(OPERATE, "    function planTouched() {")


def test_handing_to_the_agent_is_a_button_not_a_mode():
    assert 'id="op-run-agent"' in PANE
    assert "agentBtn.addEventListener('click', handToAgent)" in OPERATE
    assert "_mode === 'agent'" not in OPERATE and "_mode === 'single'" not in OPERATE


# ── the run, in the operator's words ─────────────────────────────────────


def test_a_runs_card_does_not_speak_in_the_codes_names():
    card = _fn(OPERATE, "    function tacticCard(t) {")
    assert "t.kind === 'standing_timelapse' ? ''" in card
    assert "Started from the Operate Run step" in card  # recognised, and not repeated
    assert "`every ${AcquisitionPlan.intervalWords(Number(cadence))}`" in card


def test_the_clock_is_what_there_is_to_wait_for():
    run = _fn(OPERATE, "    async function renderRun() {")
    assert 'class="op-run-clock"' in run and "to the next round" in run
    assert "font: 500 28px/1 var(--op-mono);" in _rule(".op-run-clock {")


def test_the_monitor_with_every_timepoint_is_one_press_away():
    assert 'id="op-acq-monitor"' in PANE
    assert "switchTab('embryos')" in OPERATE
