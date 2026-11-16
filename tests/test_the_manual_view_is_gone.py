"""The Devices tab's "Manual" view is gone, superseded by Scope and Acquisition.

Manual was a second, standalone set of the instrument's controls (its own
light-sheet live view, laser presets, LED, snap/burst and an old timelapse
form). The Operate workspace — Scope plus Acquisition (operate.js) — now holds
all of it in one place, so the view was removed whole: its tab button, its
template block, every element id it owned, and the devices.js code that only
served it. CI drives no browser, so the removal is pinned as source here: a
reference left behind would throw only when its line ran.
"""

from __future__ import annotations

from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
DEVICES = (WEB / "static" / "js" / "devices.js").read_text(encoding="utf-8")

# Every element id the view owned started with one of these.
REMOVED_PREFIXES = ("devices-ls-", "devices-tl-", "devices-tlacc-")


def test_the_template_has_no_manual_view() -> None:
    assert 'data-view="manual"' not in INDEX
    assert "devices-view-manual" not in INDEX
    for prefix in REMOVED_PREFIXES:
        assert prefix not in INDEX, prefix
    assert "devices-laser-preset" not in INDEX


def test_devices_js_has_no_manual_view() -> None:
    assert "'manual'" not in DEVICES and '"manual"' not in DEVICES
    for prefix in REMOVED_PREFIXES:
        assert prefix not in DEVICES, prefix
    assert "devices-laser-preset" not in DEVICES


def test_the_views_list_has_no_manual() -> None:
    assert "const VIEWS = ['operate', 'map', 'details', 'optical3d'];" in DEVICES
