"""Which cards on the Bottom cam rail are open is the rig's choice.

The choice is the rig's and is kept as it is pressed (2026-10-09). The
states live in ``<storage>/config/rail_cards.json``
(routes/ui_prefs.py), every press writes one card through, each change is
a line in the settings history, and every browser hears UI_RAIL_CARDS.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core import settings_history
from gently.core.event_bus import EventType
from gently.ui.web import auth
from gently.ui.web.routes import ui_prefs

WEB = Path(__file__).resolve().parents[1] / "gently" / "ui" / "web"
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(ui_prefs, "_root", lambda: tmp_path)
    return tmp_path


def _app(bus=None):
    server = MagicMock()
    if bus is None:
        server.agent_bridge = None
    else:
        server.agent_bridge.agent._event_bus = bus
    app = FastAPI()
    app.include_router(ui_prefs.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def test_nothing_kept_reads_as_nothing(root):
    assert _app().get("/api/ui/rail-cards").json() == {"cards": {}}


def test_one_press_writes_one_card_beside_the_settings_history(root):
    c = _app()
    assert c.put("/api/ui/rail-cards", json={"cards": {"led": False}}).json() == {
        "cards": {"led": False}
    }
    assert c.put("/api/ui/rail-cards", json={"cards": {"overview": True}}).json() == {
        "cards": {"led": False, "overview": True}
    }
    kept = json.loads((root / "config" / "rail_cards.json").read_text(encoding="utf-8"))
    assert kept == {"cards": {"led": False, "overview": True}}
    assert ui_prefs.path(root).parent == settings_history.path(root).parent
    # and a fresh client reads what the rig holds
    assert _app().get("/api/ui/rail-cards").json()["cards"] == {"led": False, "overview": True}


def test_every_change_is_a_line_in_the_history_and_no_change_is_none(root):
    c = _app()
    c.put("/api/ui/rail-cards", json={"cards": {"focus": False}})
    c.put("/api/ui/rail-cards", json={"cards": {"focus": False}})
    c.put("/api/ui/rail-cards", json={"cards": {"focus": True, "stage": False}})
    changes = settings_history.read(root=root)
    keys = sorted((ch["key"], str(ch["old"]), ch["new"]) for ch in changes)
    assert keys == [
        ("views.railCards.focus", "False", True),
        ("views.railCards.focus", "None", False),
        ("views.railCards.stage", "None", False),
    ]
    assert all(ch["reach"] == "rig" and ch["via"] == "Bottom cam" for ch in changes)


def test_every_browser_is_told(root):
    bus = MagicMock()
    c = _app(bus)
    c.put("/api/ui/rail-cards", json={"cards": {"camera": False}})
    kw = bus.publish.call_args.kwargs
    assert kw["event_type"] is EventType.UI_RAIL_CARDS
    assert kw["data"] == {"cards": {"camera": False}}
    bus.publish.reset_mock()
    c.put("/api/ui/rail-cards", json={"cards": {"camera": False}})
    assert not bus.publish.called, "told of a change that was not one"


def test_bad_input_is_400(root):
    c = _app()
    for body in (
        {},
        {"cards": {}},
        {"cards": []},
        {"cards": {"lasers": True}},
        {"cards": {"led": "no"}},
    ):
        assert c.put("/api/ui/rail-cards", json=body).status_code == 400, body


def test_the_pane_reads_writes_and_listens():
    fn = OPERATE[OPERATE.index("function discloseState(key)") :]
    fn = fn[: fn.index("\n    }")]
    assert "localStorage" not in fn, "the choice is the rig's, not this browser's"
    assert "_railCards[key]" in fn
    assert "getJSON('/api/ui/rail-cards')" in OPERATE
    assert "fetch('/api/ui/rail-cards'" in OPERATE and "method: 'PUT'" in OPERATE
    assert "ClientEventBus.on('UI_RAIL_CARDS'" in OPERATE
    act = OPERATE[OPERATE.index("async function activate()") :]
    act = act[: act.index("\n    }")]
    assert "await loadRailCards();" in act
