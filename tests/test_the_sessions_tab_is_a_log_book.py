"""The Sessions tab is the rig's log book.

"build teh sessions redesign", of the drawing in
docs/workspace/mockup-sessions-v1.html and the study beside it.

It was a column of cards 339 px wide beside 1,320 px of nothing: five
sessions of 47 on screen, nothing to read down, and an opened session's
pictures 633 px down an 889 px window. It is a table with the page, one
session a line; and with one opened, the log, what the session holds, and its
record, side by side.

Measured in a browser on the rig's own sessions: 24 lines at 1920x889 and 26
at 1440x920, where there were 5; and the eleven embryos of the 12 October
night all on one screen at both sizes, where the pane was 1,751 px tall. CI
drives no browser, so the arrangement is pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
JS = (WEB / "static" / "js" / "review.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "review.css").read_text(encoding="utf-8")
PANEL = (WEB / "templates" / "_sessions_panel.html").read_text(encoding="utf-8")


def _fn(head: str) -> str:
    body = JS[JS.index(head) :]
    return body[: body.index("\n    },")]


LIST = _fn("    renderSessionList() {")
ROW = _fn("    rowHtml(s) {")


def test_the_page_is_a_bar_then_the_log_then_what_is_opened() -> None:
    order = [
        PANEL.index(x) for x in ('class="slog-bar"', 'id="session-list"', 'id="session-content"')
    ]
    assert order == sorted(order)
    for el in ("session-search", "session-filters", "session-count", "session-empties"):
        assert f'id="{el}"' in PANEL, el
    # With nothing opened the log has the page.
    assert ".review-container:not([data-open]) .session-content { display: none; }" in CSS


def test_one_session_is_one_line_with_its_facts_in_columns() -> None:
    heads = re.findall(r"th\('(\w+)', '([^']+)'", LIST)
    want = "When Emb Timepoints Every Lasted Brightfield Ended Size Project By".split()
    assert [h[1] for h in heads] == [*want, "Name or note"]
    assert ROW.count("<td") == len(heads)
    assert "height: 26px;" in CSS[CSS.index(".slog td {") :][:200]


def test_when_says_the_day_of_the_week() -> None:
    """ "on the when tab can it also state the day of the week?" """
    assert "this.whenWords(s.created_at)" in ROW
    assert "weekday: 'short'" in _fn("    whenWords(iso) {")


def test_a_heading_sorts_and_pressed_again_turns_round() -> None:
    sort = _fn("    setSort(key) {")
    assert "st.desc = st.sort === key ? !this.sortDesc(st) : this.SORTS[key].desc;" in sort
    for key, _ in re.findall(r"th\('(\w+)', '([^']+)'", LIST):
        assert f"        {key}: {{ key:" in JS, key
    # A heading is a control: it can be reached and pressed from the keyboard.
    assert 'data-sort="${key}" tabindex="0"' in LIST and "aria-sort=" in LIST
    assert "e.key === 'Enter' || e.key === ' '" in _fn("    wireLog() {")
    # The live session is the first line, whatever the order.
    assert "(b.active ? 1 : 0) - (a.active ? 1 : 0)" in _fn("    applyFilters(sessions, table) {")


def test_the_log_is_a_list_to_the_keyboard() -> None:
    """A row was a div with a click handler: no tab stop, no arrows."""
    keys = _fn("    onListKey(e) {")
    for key in ("'ArrowDown'", "'ArrowUp'", "'Enter'", "'Escape'"):
        assert key in keys, key
    assert "if (this.currentSession) this.loadSession(go.dataset.sessionId);" in keys
    assert "if (stop) stop.tabIndex = 0;" in LIST  # one row is the tab stop
    assert "e.key !== '/'" in _fn("    wireLog() {")


def test_the_empty_sessions_are_one_line_with_their_number() -> None:
    foot = _fn("    renderFoot(searched, shown) {")
    assert "with nothing in" in foot and "ReviewApp.toggleEmpties()" in foot
    assert "<b>${shown.length}</b> of ${this.sessions.length}" in foot


def test_the_filters_are_one_bar_and_always_there() -> None:
    filters = _fn("    renderFilters(searchedSessions, table) {")
    assert "st.open" not in filters and "toggleFilters" not in JS
    assert 'role="group" aria-label="${def.label}"' in filters
    assert "aria-pressed=" in filters


def test_a_row_is_repainted_in_place() -> None:
    """Sizes arrive in the background. A row replaced whole between the press
    and the release of a click swallowed the click: the session did not open."""
    paint = _fn("    repaintRow(sid) {")
    assert "el.innerHTML = row.innerHTML;" in paint
    assert "el.outerHTML" not in paint


def test_an_opened_session_shows_its_pictures_first_and_its_record_beside() -> None:
    page = _fn("    renderSessionContent() {")
    assert page.index('class="session-view"') < page.index('class="session-record"')
    assert page.index('id="session-tab-content"') < page.index('class="session-record"')
    names = re.findall(r'<h3 class="srec-name">([^<]+)</h3>', page)
    assert names == ["This session", "The run", "Notes", "Take out"]
    for el in (
        "session-name-form",
        "session-filed",
        "session-stream",
        "session-export",
        "session-movies",
    ):
        assert f'id="{el}"' in page, el
    assert "ReviewApp.closeSession()" in page
    assert "delete page.dataset.open;" in _fn("    closeSession() {")


def test_every_embryo_is_on_one_screen() -> None:
    fit = _fn("    fitTiles(again) {")
    assert "for (let across = 1; across <= n; across++)" in fit
    # The room under a picture is measured, from the tile with the most to say.
    assert "c.offsetHeight - thumb.offsetHeight" in fit
    assert "if (!again) this.fitTiles(true);" in fit
    assert "repeat(var(--across, 4), var(--tile-w, 240px))" in CSS


def test_one_scrubber_moves_every_picture() -> None:
    """Each picture scrubbed on its own; the dish could not be put at one moment."""
    assert "el._showAt(t)" in _fn("    scrubAll(t) {")
    wire = _fn("    wireScrub() {")
    assert "tps.filter(x => x <= t).pop() || tps[0]" in wire
    # Leaving a picture puts it back at the page's moment, not at its last.
    assert "el.addEventListener('mouseleave', () => el._showAt(this._scrubT));" in wire
    assert 'id="session-scrub-in"' in _fn("    renderSessionContent() {")


def test_the_run_says_the_cadence_it_kept() -> None:
    kept = _fn("    keptCadence(s) {")
    assert (
        "(h * 3600) / (tp - 1)" in kept and "if (!asked || h == null || tp < 2) return '';" in kept
    )
