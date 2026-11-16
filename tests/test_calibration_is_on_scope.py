"""Calibration is on Scope, with everything it needs.

It has been in three places, and each move had a reason.

#108, from the 2026-08-07 walkthrough. Calibrate was a button in the SPIM
head's status bar and its result appeared in a different tab. The operator:
"after setting up the bottom camera and SPIM head, I feel like I'm not quite
sure what to do in gently at this point." So it became a pane of its own
between the cameras and Acquisition, with its result beside its button.

2026-11-13, the study in docs/workspace/calibration-and-acquisition.md. A
calibration is an operation on the light sheet, for the selected embryo,
judged through the light-sheet camera, and it needs the laser. The sheet, the
embryo list, the camera and the laser are all on Scope and none was on the
Calibration page, which is why the first calibration pressed for the study
spent eleven exposures on a dark laser. The owner: "calibration thing moving
to the scope page is good", and of its drawing, "agreed with the mockup, you
can make them."

So it is on Scope: one row in the Sheet panel (the fit, and the verb), and
Fit, the fifth entry of the strip above the picture (what the run looks at,
and under it how it is done). Both lessons of #108 are kept: the result sits
with the button, and the step has a name on screen.

CI drives no browser, so the arrangement is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "gently" / "ui" / "web"
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
ROSTER = (WEB / "static" / "js" / "panels" / "roster.js").read_text(encoding="utf-8")
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")

SCOPE = INDEX[INDEX.index('id="op-pane-scope"') : INDEX.index('id="op-pane-acquire"')]
SHEET = SCOPE[
    SCOPE.index('id="op-sheet"') : SCOPE.index(
        '<div class="op-inst-col">', SCOPE.index('id="op-sheet"')
    )
]
CALIB = SCOPE[SCOPE.index('id="op-calib"') :]
CALIB = CALIB[: CALIB.index('<div class="op-inst-col">')]
FIT = SCOPE[SCOPE.index('id="op-cam-cal"') : SCOPE.index('<div class="op-bar">')]
OPTIONS = SCOPE[SCOPE.index('id="op-display-cal"') :]
OPTIONS = OPTIONS[: OPTIONS.index("</details>")]


def _fn(head: str) -> str:
    body = OPERATE[OPERATE.index(head) :]
    return body[: body.index("\n    }")]


# ── the surfaces ──────────────────────────────────────────────────────────


def test_calibration_is_drawn_in_scope() -> None:
    """One list: each surface, in workflow order, and the section it is drawn in."""
    m = re.search(r"const PANE_SECTION = \{([^}]+)\}", OPERATE)
    assert m, "PANE_SECTION is gone — the surface list is spelled out in two places again"
    pairs = re.findall(r"(\w+): '(\w+)'", m.group(1))
    assert pairs == [
        ("bottom", "scope"),
        ("spim", "scope"),
        ("cal", "scope"),
        ("acquire", "acquire"),
    ], pairs


def test_one_pane_list_not_two() -> None:
    """It used to be written out in showPane and again in showPaneInitial."""
    assert "['bottom', 'spim', 'acquire']" not in OPERATE
    assert OPERATE.count("SECTIONS.forEach") == 1, "the sections are walked in more than one place"
    for caller in ("    function showPane(name) {", "    function showPaneInitial() {"):
        assert "paintPane();" in _fn(caller), (
            f"{caller.strip()} paints the surface itself — adding one now means "
            "remembering two places again"
        )


def test_it_is_not_a_page_of_its_own() -> None:
    assert 'id="op-pane-cal"' not in INDEX
    bar = INDEX[INDEX.index('id="operate-subtab-switcher"') :]
    bar = bar[: bar.index("</div>")]
    assert re.findall(r'data-view="(\w+)"', bar) == ["scope", "acquire"]


def test_the_step_has_a_name_on_screen() -> None:
    """#108: there was no next step on screen. The fit's graphs are opened
    from the Sheet panel's Fit row, beside the fit they show: "you have still
    not found a right place to move Fit tab to outside of the camera options"."""
    strip = SCOPE[SCOPE.index('id="op-source"') :]
    strip = strip[: strip.index("</span>")]
    assert "fit" not in re.findall(r'data-source="(\w+)"', strip)
    row = SCOPE[SCOPE.index('class="op-row op-fitrow"') :][:1400]
    assert 'id="op-fit-show" data-source="fit"' in row
    assert row.index('id="op-calibrate"') < row.index('id="op-fit-show"')
    assert OPERATE.count("'#op-source [data-source], #op-fit-show'") == 2
    choose = _fn("    function chooseSource(src) {")
    # A toggle: pressed with the graphs up, back to the camera before them.
    assert "if (_pane === 'cal') chooseSource(_beforeFit);" in choose
    assert "else showPane('cal');" in choose
    assert "if (name === 'cal') _beforeFit = prev === 'spim' ? _side : 'bottom';" in OPERATE
    assert "_pane === 'cal' ? 'fit'" in _fn("    function renderSource() {")
    # And Acquisition's pre-flight still leads here by name.
    assert "showPane('cal');" in _fn("    function preflightFix(action) {")


# ── the Sheet panel's row ─────────────────────────────────────────────────


def test_the_sheets_panel_shows_both_sides() -> None:
    """The rig has two views, and the panel showed whichever one the camera
    strip was on. Each side has its galvo and its piezo, always."""
    sheet = SHEET[: SHEET.index('id="op-calib"')]
    for side in ("a", "b"):
        for part in (f'id="op-gv-{side}-in"', f'id="op-gv-{side}"', f'id="op-pz-{side}-in"'):
            assert part in sheet, part
    assert sheet.index('data-side="A"') < sheet.index('data-side="B"')
    assert 'id="op-gv-in"' not in INDEX and 'id="op-pz"' not in INDEX
    # No fit and no verb in it: those are the Calibration panel's.
    assert 'id="op-calibrate"' not in sheet and 'id="op-cal-result"' not in sheet
    # Moving a side's sheet puts that side on screen, and tells the device layer.
    move = _fn("    function setAxis(side, key, v) {")
    assert "if (_side !== side) setSpimSide(side);" in move and "postLsParams();" in move
    # A side not yet read shows no number, and can still be moved.
    assert (
        "renderAxis(`op-gv-${k}`, _axisRow[side].galvo, r.galvo, p.galvo, !_poseKnown[side]);"
        in OPERATE
    )


def test_calibration_is_a_panel_of_its_own_under_the_sheets() -> None:
    """#108's other half: "its result appeared in another tab; the control
    belonged with the result". The fit of each side, the verb, its graphs and
    its settings are one panel."""
    assert SCOPE.index('id="op-sheet"') < SCOPE.index('id="op-calib"')
    for part in (
        'id="op-cal-fits"',
        'id="cal-side"',
        'id="op-calibrate"',
        'id="op-cal-abort"',
        'id="op-fit-show"',
        'id="op-cal-result"',
        'id="op-ab-align"',
    ):
        assert part in CALIB, part
    # Abort is there only while a calibration runs.
    assert re.search(r'id="op-cal-abort"[^>]* hidden>', CALIB)
    # Both sides' fits, always, from what the page already holds.
    fits = _fn("    function renderFits(emb) {")
    assert "[['A', cal], ['B', cal.B]]" in fits and "'no fit'" in fits
    assert "fetch(" not in fits and "getJSON(" not in fits


def test_several_embryos_can_be_chosen_and_calibrated_in_one_go() -> None:
    """The walk a person did by selecting each embryo and pressing Calibrate."""
    several = CALIB[CALIB.index('id="op-cal-several"') :]
    several = several[: several.index("</details>")]
    for part in ('id="op-cal-pick"', 'data-pick-set="unfitted"', 'id="op-cal-then-align"'):
        assert part in several, part
    assert 'id="op-cal-all"' in several
    walk = _fn("    async function calibrateAll() {")
    assert "Object.assign({ embryo_ids: ids, align }, calibrationSettings())" in walk
    assert "(d.why || {})[id]" in walk  # each failure with its reason
    # Aligning needs both sides asked for.
    assert "if (align && _calSide !== 'AB') align.checked = false;" in OPERATE
    # It is never greyed out: ticking it sets the side it needs.
    assert "align.disabled" not in OPERATE
    assert "if (thenAlign.checked && side && side.value !== 'AB') {" in OPERATE
    assert "sets Side to A then B" in several
    # Until somebody chooses, the ones with no fit on the side asked for.
    assert "all.filter(lacksAFit).forEach(e => _calPick.add(e.id));" in OPERATE


def test_the_row_is_on_screen_with_any_camera() -> None:
    assert "data-src" not in SHEET
    # Drawn with the instrument, from what the page already holds.
    assert "renderFitRow();" in _fn("    function renderScope() {")
    row = _fn("    function renderFitRow() {")
    assert "fetch(" not in row and "getJSON(" not in row
    assert "fitted ? 'Recalibrate' : 'Calibrate'" in row
    # The fit of the side chosen: each side has its own.
    assert "const c = sideFit(emb);" in row
    assert "renderFits(emb);" in row
    # While several embryos are walked the line is the walk's.
    assert "$('op-cal-all').dataset.busy) { renderFits(emb); return; }" in row


def test_pressing_it_brings_up_what_it_looks_at() -> None:
    """From the bottom camera or a live sheet: the run takes the light-sheet
    camera for itself, so that surface is left (its live view stops) and Fit
    comes up before anything is sent."""
    fn = _fn("    async function calibrateSelected(opts) {")
    assert fn.index("if (_pane !== 'cal') showPane('cal');") < fn.index("/calibrate`")
    assert fn.index("toastFail('Select an embryo first')") < fn.index("showPane('cal')")


# ── the Fit view ──────────────────────────────────────────────────────────


def test_the_fit_view_holds_what_a_run_looks_at() -> None:
    for part in (
        'id="op-cal-method"',  # what it is about to do, before it does it
        'id="op-cal-refused"',  # why it would not start, and the way past
        'id="op-cal-progress"',  # the frames, as they land
        'id="op-preview"',
        'id="op-cal-kept"',  # what the last run kept
        'id="op-cal-kept-all"',  # and the way to every run: the archive
    ):
        assert part in FIT, part
    # Kesavan on the walkthrough: "it should show what is the method it is
    # going to use to calibrate". And the LED-not-laser confusion #106 turned on.
    assert "laser" in FIT.lower()
    assert 'data-src="cal" hidden' in FIT[:200]


def test_the_settings_are_folded_under_the_verb() -> None:
    """Method, depth, what More... opens, borrowing and clearing: folded in
    the Calibration panel, there whichever camera is on screen."""
    assert '<details class="op-calfit-opts" id="op-display-cal">' in CALIB
    assert CALIB.index('id="op-calibrate"') < CALIB.index('id="op-display-cal"')
    assert 'data-src="cal"' not in CALIB
    assert 'id="cal-adv"' in OPTIONS and 'id="cal-adv"' not in FIT
    for part in ('id="cal-method"', 'id="cal-zbuf"', 'id="cal-more"'):
        assert part in OPTIONS, part
    for part in ('id="op-cal-borrow"', 'id="op-cal-clear"'):
        assert part in OPTIONS, part
    assert 'id="op-calibrate"' not in OPTIONS


def test_the_instrument_does_not_move_when_fit_is_chosen() -> None:
    """The box is as wide as the bottom camera's square, so the columns beside
    it keep their places. Measured: 638 px wide at 1920 by 944 with a camera
    up and with Fit up. Its height is what the settings under it leave: they
    are a heading and three named lines now, taller than Display's one."""
    box = CSS[CSS.index(".op-pane-scope .op-calfit {") :][:520]
    assert "aspect-ratio: auto;" in box and "flex: 1 1 0;" in box
    assert (
        "width: calc(100cqh - var(--op-viewbar-h) - var(--op-bar-h) - var(--op-display-h)"
        " - 3 * var(--op-view-gap));"
    ) in box


def test_align_is_a_stage_move_set_apart_and_both_sides_is_one_press() -> None:
    """Align is not one more way to a fit: it is on a line of its own in the
    Calibration panel and says it is a stage move."""
    assert 'class="op-actions cal-align"' in CALIB and "a stage move" in CALIB
    assert CALIB.index('id="op-cal-several"') < CALIB.index('id="op-ab-align"')
    # Both sides in one press, for a script as much as for a person.
    assert '<option value="AB"' in CALIB and "A then B" in CALIB
    assert "if (_calSide === 'AB') body.side = 'both';" in OPERATE


def test_everything_a_calibration_needs_is_on_the_one_screen() -> None:
    for part in ('id="op-erail-list"', 'id="op-light-host"', 'id="op-sheet"', 'id="op-cam-cal"'):
        assert part in INDEX[INDEX.index('id="op-body"') : INDEX.index('id="op-pane-acquire"')], (
            part
        )


def test_nothing_was_lost_in_the_move() -> None:
    """Every element the calibration functions write to is on the page once."""
    ids = (
        "op-cal-method op-cal-target op-cal-result op-cal-kept op-cal-kept-say op-cal-kept-open "
        "op-cal-kept-strip cal-method cal-edges cal-zbuf cal-more cal-adv cal-adv-bounds cal-gtop "
        "cal-gbot cal-estep cal-erange cal-etol cal-inset cal-adv-note cal-reset op-cal-borrow-row "
        "op-cal-borrow-from op-cal-borrow op-cal-all op-cal-clear op-calibrate op-cal-abort "
        "op-cal-borrow-note op-cal-refused op-cal-refused-why op-cal-anyway op-cal-progress "
        "op-preview op-preview-img op-preview-title op-preview-meta"
    ).split()
    for el in ids:
        assert INDEX.count(f'id="{el}"') == 1, el
        assert f'id="{el}"' in SCOPE, el


# ── the LED ───────────────────────────────────────────────────────────────


def test_leaving_fit_closes_the_led() -> None:
    """The calibrate path never did, which is half of #106."""
    block = OPERATE[OPERATE.index("        cal: {") :]
    block = block[: block.index("\n        }")]
    assert "forceLedOff()" in block


def test_coming_to_fit_from_the_sheet_closes_it_too() -> None:
    """Going to the Calibration page left Scope, and leaving Scope closed the
    LED. Fit is inside Scope, so the rule is said for it."""
    panes = OPERATE[OPERATE.index("    const PANES = {") :]
    block = panes[panes.index("        spim: {") :]
    block = block[: block.index("\n        }")]
    assert "if (!inScope(to) || to === 'cal') forceLedOff();" in block


# ── a refusal ─────────────────────────────────────────────────────────────


def test_a_refusal_points_at_what_puts_it_right() -> None:
    """The server cannot tell an unlit sheet from a raised head from a stage
    that is somewhere else: its advice is to check all three. The page can
    read all three, and their panels are on screen beside the refusal."""
    assert "const points = pointAtWhatIsWrong();" in _fn("    function showRefusal(err) {")
    point = _fn("    function pointAtWhatIsWrong() {")
    assert "RunPreflight.calibrationPoints({" in point
    for fact in ("LightPanel.emitting(light)", "ledIsOpen()", "fd.pos()", "atSelected()"):
        assert fact in point, fact
    m = re.search(r"const POINTED = \{([^}]+)\}", OPERATE)
    assert m
    for panel, el in re.findall(r"(\w+): '([\w-]+)'", m.group(1)):
        assert f'id="{el}"' in SCOPE, (panel, el)
    assert ".op-panel.is-pointed {" in CSS
    # A refusal put away takes its pointing with it.
    assert "unpoint();" in _fn("    function hideRefusal() {")


# ── the dish ──────────────────────────────────────────────────────────────


def test_the_rail_shows_which_embryos_lack_a_fit() -> None:
    """So a refusal at Start is visible beforehand, from any surface."""
    assert "showFit: true" in OPERATE
    # Same field the server-side gate checks.
    assert "slope_um_per_deg" in ROSTER


def test_fit_draws_the_runs_graphs_and_stands_apart_from_the_cameras():
    """ "the Fit tab in the camera views of Scope ... is bit out of place. also
    it shows the image based graphs and not the native graphs we worked on for
    calibration." Fit showed the saved pictures of a run's graphs; it draws
    them from the run's numbers, with the Calibration tab's own drawing."""
    web = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static"
    archive = (web / "js" / "calibration-archive.js").read_text(encoding="utf-8")
    operate = (web / "js" / "operate.js").read_text(encoding="utf-8")
    css = (web / "css" / "operate.css").read_text(encoding="utf-8")
    # One drawing, used by both.
    assert "function graphsHtml(_rec, _steps, _at) {" in archive
    assert "if (host) host.innerHTML = graphsHtml(_rec, _steps, _at);" in archive
    assert "return { ...pure, show, refresh, graphsHtml };" in archive
    kept = operate[operate.index("    async function renderCalKept(emb) {") :]
    kept = kept[: kept.index("    function calImageTitle(i) {")]
    assert "arc.graphsHtml(record, arc.steps(images), -1)" in kept
    assert kept.index("arc.graphsHtml(") < kept.index("op-cal-kept-img")  # pictures only without it
    # One graph at a time, by name, opening on the fit.
    assert "if (drawn) tabGraphs(strip);" in kept
    assert "show(figs.length - 1);" in operate
    # Not in the camera strip at all: lit in the Fit row while its graphs are up.
    assert "#op-fit-show.is-on {" in css
