"""The Calibration tab shows the runs that are on disk.

"calibration thing moving to the scope page is good, but at the same time,
not sure how we might access teh raw calibration images though -- does that
go to the calibrations page?"

It does. The tab showed only the copies pushed to the page while a
calibration ran: empty after a restart, and with no place for a run that was
refused or aborted, which is the run somebody wants to look at. Every run is
on disk with each exposure it took (tests/test_calibration_record.py), and
the tab now opens on them: the runs, one raw exposure over the run's strip,
the run's record.

CI drives no browser, so the structure is pinned here and the wording in
tests/js/calibration-archive.test.mjs.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
JS = WEB / "static" / "js"
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
ARCHIVE = (JS / "calibration-archive.js").read_text(encoding="utf-8")
GALLERY = (JS / "gallery.js").read_text(encoding="utf-8")
APP = (JS / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")

TAB = INDEX[INDEX.index('<div id="calibration-content"') : INDEX.index("<!-- Events Tab -->")]
MANAGER = GALLERY[
    GALLERY.index("const CalibrationManager = {") : GALLERY.index("    handleNewImage(newImage) {")
]


def test_the_tab_opens_on_the_runs_kept_on_disk():
    views = re.findall(r'<button class="view-btn( active)?" data-view="(\w+)"', TAB)
    assert views == [(" active", "runs"), ("", "profile"), ("", "gallery")]
    assert "currentView: 'runs'," in MANAGER
    # The pushed-image views are still there, and start out of sight.
    assert '<div class="calibration-container" id="calibration-live" hidden>' in TAB
    assert 'id="cal-archive" data-runs="none"' in TAB


def test_the_archive_has_the_three_zones_and_everything_the_script_writes_to():
    for part in ("cal-arc-runs", "cal-arc-view", "cal-arc-side", "cal-arc-empty"):
        assert f'class="{part}"' in TAB or f"{part}" in TAB, part
    for el in re.findall(r"\$\('(cal-arc-[\w-]+)'\)", ARCHIVE):
        assert f'id="{el}"' in TAB, el
    for el in re.findall(r"b\.id === '(cal-arc-[\w-]+)'", ARCHIVE):
        assert f'id="{el}"' in TAB, el
    # In the order a run is read: its runs, its picture, its record.
    assert TAB.index("cal-arc-runs") < TAB.index("cal-arc-view") < TAB.index("cal-arc-side")


def test_it_reads_the_disk_and_not_what_was_pushed_to_the_page():
    assert "'/api/calibration/records'" in ARCHIVE
    assert "/api/calibration/records/${enc(run.embryo_id)}/${enc(run.run)}" in ARCHIVE
    assert "state.calibration" not in ARCHIVE
    # Loaded before the tab's manager, which calls it.
    assert INDEX.index("/static/js/calibration-archive.js") < INDEX.index("/static/js/gallery.js")


def test_it_is_read_when_the_tab_is_come_to_and_not_on_every_pushed_image():
    # render() runs for each image a live calibration pushes; a read there
    # would put the archive back on its first exposure while it is looked at.
    render = MANAGER[MANAGER.index("    render() {") : MANAGER.index("    /** One of the archive")]
    assert "CalibrationArchive" not in render
    show = MANAGER[MANAGER.index("    showView() {") : MANAGER.index("    entered() {")]
    assert "CalibrationArchive.show" not in show
    entered = MANAGER[
        MANAGER.index("    entered() {") : MANAGER.index("    switchView(viewName) {")
    ]
    assert "this.currentView === 'runs'" in entered and "CalibrationArchive.show()" in entered
    switch = MANAGER[MANAGER.index("    switchView(viewName) {") :]
    assert "this.entered();" in switch
    assert (
        "if (tabName === TABS.CALIBRATION) "
        "{ renderCalibrationGallery(); CalibrationManager.entered(); }"
    ) in APP


def test_only_the_newest_answer_draws():
    # A run is pressed while another is still being read.
    assert ARCHIVE.count("const ask = ++_asked;") == 2
    assert ARCHIVE.count("if (ask !== _asked) return;") == 2


def test_its_click_targets_have_names_of_their_own():
    # The page's body carries data-run (the run's state). closest('[data-run]')
    # from the picture climbed past the archive to it, and pressing a raw
    # exposure selected "run NaN": the viewer never opened.
    for name in ("data-arc-run", "data-arc-frame", "data-arc-plot"):
        assert f"closest('[{name}]')" in ARCHIVE, name
    assert "closest('[data-run]')" not in ARCHIVE
    assert 'data-run="' not in ARCHIVE and 'data-frame="' not in ARCHIVE


def test_an_exposure_opens_with_its_counts_and_can_be_found_on_disk():
    assert "u16: i.u16" in ARCHIVE  # the viewer that reads values, not a picture of them
    assert "what: 'calibration_image'" in ARCHIVE and "what: 'calibration_run'" in ARCHIVE
    for el in ("cal-arc-show", "cal-arc-fiji", "cal-arc-folder", "cal-arc-recal"):
        assert f'id="{el}"' in TAB, el


def test_recalibrate_goes_to_the_instrument_with_the_embryo_selected():
    recal = ARCHIVE[
        ARCHIVE.index("    function recalibrate() {") : ARCHIVE.index("    function wire()")
    ]
    assert "switchTab('devices')" in recal
    assert "OperateManager.roster.select(_rec.embryo_id);" in recal
    assert "OperateManager.roster.goTo('cal');" in recal


def test_what_is_hidden_stays_hidden():
    # Both containers set a display, which would outrank the hidden attribute.
    assert ".calibration-container[hidden], .cal-archive[hidden] { display: none; }" in CSS
    # With no run kept the page says so, in place of three empty zones.
    assert '.cal-archive[data-runs="some"] > .cal-arc-empty { display: none; }' in CSS
    assert "No calibration has been kept in this session yet." in TAB
