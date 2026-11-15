"""The Sessions list is drawn when it arrives, not when the projects do.

"Need to go over the sessions tab ... also made super efficient in loading
times."

The tab asked for the sessions and the projects together and waited for both
before it drew a row. The sessions answer in about 60 ms on the rig's data;
the projects took 240 ms (tests/test_what_a_plan_item_waits_on_is_read_once.py
is about why). All the projects add to the list is a project's name on a row
and in the filters. Measured in a browser on a copy of the rig's sessions, the
first rows appeared 280 ms after the tab was opened, and 80 ms after this.

CI drives no browser, so the order is pinned here.
"""

from __future__ import annotations

from pathlib import Path

REVIEW = (
    Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "static" / "js" / "review.js"
).read_text(encoding="utf-8")

LOAD = REVIEW[
    REVIEW.index("    async loadSessions() {") : REVIEW.index("    /** Is the Sessions tab")
]


def test_the_rows_are_drawn_before_the_projects_are_waited_for():
    asked = LOAD.index("const projects = this.loadProjects();")
    listed = LOAD.index("const resp = await fetch('/api/sessions');")
    drawn = LOAD.index("this.renderSessionList();")
    waited = LOAD.index("projects.then(")
    # Asked for beside the list, so the two are in flight together.
    assert asked < listed < drawn < waited
    assert "Promise.all([fetch('/api/sessions'), this.loadProjects()])" not in REVIEW


def test_the_rows_are_drawn_again_when_the_projects_come():
    then = LOAD[LOAD.index("projects.then(") :]
    then = then[: then.index("});") + 3]
    assert "this.renderSessionList();" in then
    # A session opened in the meantime names its projects too.
    assert "this.renderFiled(this.currentSession)" in then


def test_an_older_answer_does_not_draw_over_a_newer_one():
    # Two loads can be in flight (the list reloads when a run ends): only the
    # newest draws, whichever answers last.
    assert "const run = ++this._listRun;" in LOAD
    assert "if (run !== this._listRun) return;" in LOAD
    assert "_listRun: 0," in REVIEW
