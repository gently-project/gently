"""Every page shows its times in the microscope's zone, found by itself.

"can gently pick up timezones from the local computer?" — "yes add tzlocal".
Settings › Time zone wins when it is set. Empty, the page carries the zone of
the computer Gently runs on (tzlocal, which knows Windows' own zone names as
well as the IANA ones). When that cannot be told either, the page carries
none, and each browser shows its own.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from gently.ui.web.routes import pages

TEMPLATES = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web" / "templates"


@pytest.fixture(autouse=True)
def _found_afresh():
    pages._this_computers_zone.cache_clear()
    yield
    pages._this_computers_zone.cache_clear()


def _set(monkeypatch, zone: str) -> None:
    monkeypatch.setattr(
        pages, "settings", SimpleNamespace(ui=SimpleNamespace(time_zone=zone, ux_v2=True))
    )


def test_with_no_zone_set_a_page_carries_this_computers(monkeypatch):
    _set(monkeypatch, "")
    monkeypatch.setattr("tzlocal.get_localzone_name", lambda: "Asia/Tokyo")
    assert pages.time_zone() == "Asia/Tokyo"


def test_a_zone_set_in_settings_wins(monkeypatch):
    _set(monkeypatch, "America/New_York")
    monkeypatch.setattr("tzlocal.get_localzone_name", lambda: "Asia/Tokyo")
    assert pages.time_zone() == "America/New_York"


def test_a_computer_that_cannot_say_leaves_each_browser_its_own(monkeypatch, caplog):
    _set(monkeypatch, "")

    def unset():
        raise RuntimeError("no zone configured on this computer")

    monkeypatch.setattr("tzlocal.get_localzone_name", unset)
    assert pages.time_zone() == ""
    assert "Could not tell this computer's time zone" in caplog.text


def test_the_page_says_the_zone_it_shows_times_in(monkeypatch):
    _set(monkeypatch, "")
    monkeypatch.setattr("tzlocal.get_localzone_name", lambda: "Asia/Tokyo")
    server = SimpleNamespace(gate_passed=True, templates=Jinja2Templates(directory=str(TEMPLATES)))
    app = FastAPI()
    app.include_router(pages.create_router(server))
    html = TestClient(app).get("/").text
    assert '<meta name="gently-time-zone" content="Asia/Tokyo">' in html
