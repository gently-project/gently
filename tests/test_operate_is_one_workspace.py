"""Operate is one workspace: the dish, what the rig sees, the instrument.

Until 2026-11-13 the bottom camera and the SPIM head were two panes. Each
assembled its own rail around its own frame, so the same control was in a
different place, or missing, depending on which camera was up: the stage pad
and the LED's brightness only beside the bottom camera, the head and the laser
only beside the light sheet. What did not fit scrolled, and three rows of
chrome above the panes left a 1920 px window a 373 px picture.

"there is still no good way to place the panels on the screen. what is the
fundamental problem? ... why is this gui not as good as the microscope guis
traditionally made"

The answer was that nothing had a place. So Scope: three zones in one row —
the dish (find, embryos, fields, overview frames), what the rig sees (one
frame, from the camera chosen in the strip above it), and the instrument
(light, sheet, head, stage) — in which every panel has one place and keeps
it, and the only things that change with the camera are the camera's own.
docs/workspace/README.md has the reasoning and the measurements.

CI drives no browser, so the structure is pinned as source. What is pinned is
what makes it a workspace; how it looks was checked by hand on the simulated
rig (tools/sim_rig.py) at 1920x889 and at the desktop app's 1440x920.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
DEVICES = (WEB / "static" / "js" / "devices.js").read_text(encoding="utf-8")
SHELL = (WEB / "static" / "js" / "shell.js").read_text(encoding="utf-8")
TEMP = (WEB / "static" / "js" / "temperature-graph.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")
RIG_CSS = (WEB / "static" / "css" / "rig-menu.css").read_text(encoding="utf-8")

VIEW = INDEX[INDEX.index('id="devices-view-operate"') : INDEX.index('id="devices-view-map"')]
RAIL = INDEX[INDEX.index('id="op-erail"') : INDEX.index('class="op-panearea"')]
SCOPE = INDEX[INDEX.index('id="op-pane-scope"') : INDEX.index('id="op-pane-cal"')]
FRAME = SCOPE[SCOPE.index('class="op-view"') : SCOPE.index('<aside class="op-inst"')]
INSTRUMENT = SCOPE[SCOPE.index('<aside class="op-inst"') :]
TOOLBAR = INDEX[
    INDEX.index('class="devices-header-bar"') : INDEX.index('id="devices-view-operate"')
]


def _fn(src: str, head: str) -> str:
    body = src[src.index(head) :]
    return body[: body.index("\n    }")]


def _rule(css: str, selector: str) -> str:
    m = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"no rule for {selector}"
    return m.group(1)


# ── three zones, one of each thing ───────────────────────────────────────


def test_both_cameras_are_one_section_of_the_page() -> None:
    assert 'id="op-pane-bottom"' not in INDEX and 'id="op-pane-spim"' not in INDEX
    for cam in ('id="op-cam-bottom"', 'id="op-cam-spim"'):
        assert cam in FRAME, f"{cam} is not in the one frame column"
    sections = re.findall(r'<section class="op-pane[^"]*" id="(op-pane-\w+)"', VIEW)
    assert sections == ["op-pane-scope", "op-pane-cal", "op-pane-acquire"], sections


def test_the_dish_is_the_rail_and_holds_what_is_on_it() -> None:
    order = [
        RAIL.index('id="op-marking-host"'),
        RAIL.index('id="op-erail-list"'),
        RAIL.index('id="op-frail-list"'),
        RAIL.index('id="op-overview-host"'),
    ]
    assert order == sorted(order), "the rail is not find, embryos, fields, overview frames"
    # Finding acts on the bottom camera's picture; it used to be a full-width
    # strip under the frame, which took the frame's height.
    assert 'id="op-marking-host"' not in SCOPE
    assert "flex: 0 0 280px" in _rule(CSS, ".op-embryos")


def test_the_instrument_is_four_panels_in_two_columns_whose_order_never_changes() -> None:
    cols = INSTRUMENT.split('<div class="op-inst-col">')[1:]
    assert len(cols) == 2
    assert cols[0].index('id="op-light-host"') < cols[0].index('id="op-sheet"')
    assert cols[1].index('id="op-gauge-fd"') < cols[1].index('id="op-stage-panel"')
    # The stage's own things are in its panel: the pad, the bottom
    # objective's focus, and what "centre" means.
    stage = cols[1][cols[1].index('id="op-stage-panel"') :]
    for part in ('id="op-stage-host"', 'id="op-gauge-bz"', 'id="op-align-set"'):
        assert part in stage, part
    assert "flex: 1 1 300px" in _rule(CSS, ".op-inst-col")


def test_nothing_in_the_instrument_or_the_dish_belongs_to_one_camera() -> None:
    """The LED lights either camera; the head and the stage are the same
    head and stage. Only what is the camera's own changes with the camera."""
    assert "data-src" not in INSTRUMENT
    assert "data-src" not in RAIL
    owned = re.findall(r'id="([\w-]+)"[^>]*data-src="(\w+)"', FRAME)
    assert sorted(owned) == sorted(
        [
            ("op-cam-toggle", "bottom"),
            ("op-spim-toggle", "spim"),
            ("op-cam-panel-bottom", "bottom"),
            ("op-cam-panel-spim", "spim"),
            ("op-cam-bottom", "bottom"),
            ("op-cam-spim", "spim"),
            ("op-display-bottom", "bottom"),
            ("op-display-spim", "spim"),
        ]
    ), owned
    # The page starts on the bottom camera: the light sheet's own are hidden.
    for tag in re.findall(r"<[^>]*data-src=\"spim\"[^>]*>", FRAME):
        assert " hidden" in tag, tag
    for tag in re.findall(r"<[^>]*data-src=\"bottom\"[^>]*>", FRAME):
        assert " hidden" not in tag, tag


# ── the strip chooses the camera ─────────────────────────────────────────


def test_one_strip_names_every_camera() -> None:
    strip = FRAME[FRAME.index('id="op-source"') :]
    strip = strip[: strip.index("</span>")]
    assert re.findall(r'data-source="(\w+)"', strip) == ["bottom", "A", "B", "Multi"]
    assert re.findall(r">([^<>]+)</button>", strip) == ["Bottom cam", "SPIM A", "SPIM B", "Multi"]


def test_the_strip_shows_the_surface_and_the_side_as_they_are() -> None:
    fn = _fn(OPERATE, "    function renderSource() {")
    assert "_pane === 'bottom' ? 'bottom' : _pane === 'spim' ? _side : null" in fn
    # It is redrawn whenever either changes: the surface, and the side.
    assert "renderSource();" in _fn(OPERATE, "    function paintPane() {")
    assert "renderSource();" in _fn(OPERATE, "    function renderPose() {")


def test_only_the_cameras_own_things_change_with_the_camera() -> None:
    paint = _fn(OPERATE, "    function paintPane() {")
    assert "document.querySelectorAll('#op-pane-scope [data-src]')" in paint
    assert "el.hidden = el.dataset.src !== _pane;" in paint
    assert "disabled" not in paint


def test_no_control_is_switched_off_by_which_surface_is_up() -> None:
    """THE INVARIANT, from the top of operate.js: `_pane` is read for render
    dispatch and for which stream owns MMCore, and never to disable a
    control. Putting both cameras on one screen is where that would creep
    back in ("the sheet belongs to the SPIM view, grey it out")."""
    code = "\n".join(ln for ln in OPERATE.splitlines() if not ln.strip().startswith(("//", "*")))
    for line in code.splitlines():
        if "_pane" in line:
            assert "disabled" not in line, line.strip()
    axis = _fn(OPERATE, "    function renderAxis(id, row, ext, v, off) {")
    assert "_pane" not in axis
    pose = _fn(OPERATE, "    function renderPose() {")
    assert "const multi = _side === 'Multi';" in pose and "_pane" not in pose


def test_scope_in_the_toolbar_comes_back_to_the_camera_it_last_showed() -> None:
    show = _fn(OPERATE, "    function showPane(name) {")
    assert "if (name === 'scope') name = _scope;" in show
    assert "if (inScope(name)) _scope = name;" in show
    # Everything that already asked for a camera's surface by name still can.
    assert "goTo: pane => showPane(pane)," in OPERATE
    assert "showPane('bottom');" in _fn(OPERATE, "    function onMarkingImage(d) {")


def test_finding_brings_the_bottom_cameras_frame_up() -> None:
    """Detect is in the rail beside whichever camera is up, and what it finds
    is drawn on the bottom camera's frame."""
    fn = _fn(OPERATE, "    async function runDetect(opts) {")
    assert fn.index("showPane('bottom');") < fn.index("_detecting = true;")


# ── the frame takes the height there is ──────────────────────────────────


def test_the_frame_is_sized_from_the_room_there_is_with_no_script_measuring() -> None:
    pane = _rule(CSS, ".op-pane-scope")
    assert "container-type: size" in pane
    assert "grid-template-columns: auto minmax(var(--op-inst-min), 1fr)" in pane
    cam = _rule(CSS, ".op-pane-scope .op-cam")
    assert (
        "height: calc(100cqh - var(--op-viewbar-h) - var(--op-bar-h) - var(--op-display-h)"
        " - 3 * var(--op-view-gap))" in cam
    )
    assert "aspect-ratio: var(--cam-ar, 1 / 1)" in cam
    # A narrow window shrinks the frame's box, never the instrument.
    assert "max-width: calc(100cqw - var(--op-inst-min) - var(--op-col-gap))" in cam
    # What sits around the frame has a fixed height, or the arithmetic is a guess.
    for part, var in (
        (".op-viewbar", "--op-viewbar-h"),
        (".op-pane-scope .op-bar", "--op-bar-h"),
        (".op-pane-scope .op-block-display", "--op-display-h"),
    ):
        assert f"height: var({var})" in _rule(CSS, part), part


def test_what_sits_under_the_frame_cannot_widen_its_column() -> None:
    for part in (".op-pane-scope .op-bar", ".op-pane-scope .op-block-display"):
        assert "contain: inline-size" in _rule(CSS, part), part


def test_a_small_window_stacks_and_scrolls_instead_of_squeezing() -> None:
    small = re.search(r"@container operate \(max-width: 1060px\) \{(.*?)\n\}", CSS, re.S)
    assert small, "the workspace has no small-window layout"
    body = small.group(1)
    assert re.search(r"\.op-body\s*\{[^}]*flex-direction:\s*column[^}]*overflow-y:\s*auto", body)
    # The frame first, then the instrument, then the dish.
    assert re.search(r"\.op-panearea\s*\{[^}]*order:\s*1", body)
    assert re.search(r"\.op-embryos\s*\{[^}]*order:\s*2", body)


# ── one row of chrome ────────────────────────────────────────────────────


def test_the_surfaces_and_the_views_are_one_strip() -> None:
    assert 'class="op-subnav"' not in INDEX, "the second row of navigation is back"
    assert 'class="devices-title"' not in INDEX
    surfaces = TOOLBAR[TOOLBAR.index('id="operate-subtab-switcher"') :]
    surfaces = surfaces[: surfaces.index("</div>")]
    assert re.findall(r'data-view="(\w+)"', surfaces) == ["scope", "cal", "acquire"]
    views = TOOLBAR[TOOLBAR.index('id="devices-view-switcher"') :]
    views = views[: views.index("</div>")]
    assert re.findall(r'data-view="(\w+)"', views) == ["map", "details", "optical3d", "manual"]


def test_a_surface_pressed_from_another_view_comes_back_to_operate_first() -> None:
    wire = OPERATE[OPERATE.index("if (_wired) return;") :]
    hook = wire[wire.index("initViewSwitcher('operate-subtab-switcher'") :][:600]
    assert "if (!_active && typeof DevicesManager !== 'undefined')" in hook
    assert hook.index("DevicesManager.switchView('operate');") < hook.index("showPane(name);")
    # And with another view up, none of the surfaces is marked as the one on screen.
    off = _fn(OPERATE, "    function deactivate() {")
    assert "updateViewButtons('operate-subtab-switcher', '');" in off
    assert "return { init, handlePayload, switchView };" in DEVICES


def test_halt_is_once_in_the_toolbar_and_wired() -> None:
    assert INDEX.count('id="op-halt"') == 1 and 'id="op-halt"' in TOOLBAR
    assert re.search(
        r"\$\('op-halt'\)[^;]*;\s*if \(halt\) halt\.addEventListener\('click', haltMotion\)",
        OPERATE,
    )
    assert "background: var(--accent-red)" in _rule(CSS, ".devices-halt")


def test_the_page_gives_the_workspace_its_edges() -> None:
    sw = _fn(DEVICES, "    function switchView(viewName) {")
    assert "box.dataset.view = viewName;" in sw
    assert "padding: 8px 10px" in _rule(CSS, '.devices-container[data-view="operate"]')
    # The header's strip repeats what this tab's toolbar and the status bar
    # say; here its row goes to the picture.
    assert (
        "body.ux-v2 .app-main:has(> #devices-content.active) > .v2-strip { display: none; }" in CSS
    )


def test_the_water_is_one_reading_in_the_toolbar_and_its_chart_lies_over_the_page() -> None:
    assert 'id="devices-tempwrap-toggle"' in TOOLBAR and 'id="devices-tempwrap-now"' in TOOLBAR
    wrap = INDEX[INDEX.index('id="devices-tempwrap"') :][:400]
    assert "devices-tempwrap-toggle" not in wrap, "the strip under every view is back"
    assert "position: absolute" in _rule(RIG_CSS, ".devices-tempwrap")
    assert ".devices-tempwrap.is-collapsed { display: none; }" in RIG_CSS
    # Hidden until a sample arrives, like the chart it opens.
    vis = _fn(TEMP, "    function setWrapVisible(on) {")
    assert 'document.getElementById("devices-tempwrap-toggle")' in vis
    assert "btn.hidden = !on;" in vis


def test_the_rail_of_destinations_starts_as_icons_on_this_tab() -> None:
    """156 px of names is 156 px the picture and the panels do not get: at
    the desktop window's 1440 px it is the difference between a frame beside
    its panels and a frame above them. The choice made there is kept for
    there, apart from the choice for every other tab."""
    assert "const COLLAPSE_KEY_DEVICES = 'gently.rail.collapsed.devices';" in SHELL
    assert "const WIDE_TABS = ['devices'];" in SHELL
    fn = _fn(SHELL, "    function collapsedFor(tab) {")
    assert "saved === '1' || (saved == null && startsCollapsed(tab))" in fn
    assert "applyCollapsed(collapsedFor(tabName));" in SHELL


# ── what the frame's caption says ────────────────────────────────────────


def test_the_caption_says_what_is_arriving() -> None:
    bar = FRAME[FRAME.index('class="op-bar"') :]
    assert 'id="op-view-meta"' in bar[: bar.index("</div>")]
    note = _fn(OPERATE, "    function noteFrame(pane) {")
    # At most once a second: a per-frame text change is one more thing for
    # the page, and the session recorder, to do on every frame.
    assert "if (now - _viewMetaAt >= 1000) renderViewMeta();" in note
    meta = _fn(OPERATE, "    function renderViewMeta() {")
    assert "if (el.textContent !== text) el.textContent = text;" in meta
    # The sensor's size is the one the pixel fetch states, not the preview's
    # size times its downsample (2050 for a 2048 sensor).
    assert "_frameDims[pane] = `${meta.sourceWidth}×${meta.sourceHeight}`" in OPERATE
