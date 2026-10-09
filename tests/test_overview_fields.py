"""The overview fields are set where the picture is, and kept with the session.

Ryan, before the 2026-10-09 demo: "some of these features would benefit from
being present in the bottom cam page, as opposed to being available to set
in the acquisition page … when accessed through the acquisition page, one
needs to go back to the cam view to live mode, and then do those things."

So the fields of view the brightfield overview is taken from are a list of
their own — the same shape as the embryos' — built on the Bottom cam pane
beside the stage pad and the live view, kept in the session so a reload and
the Acquisition pane find it, and read by the plan as "taken from the
fields". The overview's light, LED brightness, exposure and its dark and
flat references moved to the same pane, for the same reason: the flat needs
the stage driven to an empty part of the dish, and the light is chosen by
looking at the picture.

CI runs no browser, so the wiring is pinned as source; the route and the
store are exercised for real.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.core.file_store import FileStore
from gently.ui.web import auth
from gently.ui.web.routes import brightfield as bf_routes

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "gently" / "ui" / "web"
INDEX = (WEB / "templates" / "index.html").read_text(encoding="utf-8")
OPERATE = (WEB / "static" / "js" / "operate.js").read_text(encoding="utf-8")
PANEL = (WEB / "static" / "js" / "panels" / "fields.js").read_text(encoding="utf-8")
REFS = (WEB / "static" / "js" / "panels" / "brightfield-refs.js").read_text(encoding="utf-8")
STORE_JS = (WEB / "static" / "js" / "status-store.js").read_text(encoding="utf-8")
CSS = (WEB / "static" / "css" / "operate.css").read_text(encoding="utf-8")


@pytest.fixture
def store(tmp_path):
    s = FileStore(root=tmp_path / "data")
    s.create_session("s1")
    return s


def _app(store, sid="s1"):
    server = MagicMock()
    agent = server.agent_bridge.agent
    agent.store = store
    agent.session_id = sid
    app = FastAPI()
    app.include_router(bf_routes.create_router(server))
    app.dependency_overrides[auth.require_control] = lambda: True
    return TestClient(app)


def _section(html: str, start: str, end: str) -> str:
    return html[html.index(start) : html.index(end)]


BOTTOM = _section(INDEX, 'id="op-pane-bottom"', 'id="op-pane-spim"')
ACQUIRE = _section(INDEX, 'id="op-pane-acquire"', ".op-panearea -->")
RAIL = _section(INDEX, 'id="op-erail"', ".op-panearea")


# ── the store ────────────────────────────────────────────────────────────────


class TestTheStore:
    def test_the_fields_are_a_file_in_the_session(self, store):
        path = store.save_overview_fields("s1", [{"x": -512.0, "y": 88.5}, {"x": 900, "y": -380}])
        assert path.name == "overview_fields.yaml" and path.parent == store._session_dir("s1")
        assert store.get_overview_fields("s1") == [{"x": -512.0, "y": 88.5}, {"x": 900, "y": -380}]

    def test_none_is_an_empty_list_not_an_error(self, store):
        assert store.get_overview_fields("s1") == []
        assert store.get_overview_fields("nope") == []

    def test_the_whole_list_is_replaced(self, store):
        store.save_overview_fields("s1", [{"x": 1, "y": 2}, {"x": 3, "y": 4}])
        store.save_overview_fields("s1", [{"x": 3, "y": 4}])
        assert store.get_overview_fields("s1") == [{"x": 3, "y": 4}]


# ── the route ────────────────────────────────────────────────────────────────


class TestTheRoute:
    def test_put_then_get_round_trips_in_order(self, store):
        c = _app(store)
        r = c.put(
            "/api/brightfield/fields",
            json={"fields": [{"x": "-512.4", "y": 88}, {"x": 900, "y": -380.25}]},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {
            "session_id": "s1",
            "fields": [{"x": -512.4, "y": 88.0}, {"x": 900.0, "y": -380.25}],
        }
        assert c.get("/api/brightfield/fields").json()["fields"] == [
            {"x": -512.4, "y": 88.0},
            {"x": 900.0, "y": -380.25},
        ]
        # An empty list is a list: the last field dropped must stick.
        assert c.put("/api/brightfield/fields", json={"fields": []}).status_code == 200
        assert c.get("/api/brightfield/fields").json()["fields"] == []

    def test_no_session_reads_as_no_fields(self):
        server = MagicMock()
        server.agent_bridge = None
        app = FastAPI()
        app.include_router(bf_routes.create_router(server))
        app.dependency_overrides[auth.require_control] = lambda: True
        c = TestClient(app)
        assert c.get("/api/brightfield/fields").json() == {"session_id": None, "fields": []}
        assert c.put("/api/brightfield/fields", json={"fields": []}).status_code == 503

    def test_bad_input_is_400(self, store):
        c = _app(store)
        for body in (
            {},
            {"fields": "here"},
            {"fields": [{"x": 1}]},
            {"fields": [{"x": "a", "y": 2}]},
            {"fields": [{"x": 1e9, "y": 2}]},
            {"fields": [{"x": 1, "y": 2}] * 65},
        ):
            assert c.put("/api/brightfield/fields", json=body).status_code == 400, body


# ── the pane ─────────────────────────────────────────────────────────────────


class TestWhereThingsAre:
    def test_the_fields_list_sits_in_the_rail_and_on_acquisition_like_the_embryos(self):
        assert 'id="op-frail-list"' in RAIL and 'id="op-erail-list"' in RAIL
        assert 'id="op-fields"' in ACQUIRE and 'id="op-roster"' in ACQUIRE
        assert '<script src="/static/js/panels/fields.js"></script>' in INDEX
        assert INDEX.index("panels/fields.js") < INDEX.index('src="/static/js/operate.js"')
        mounts = re.findall(r"FieldsPanel\.mount\('([^']+)'", OPERATE)
        assert set(mounts) == {"op-frail-list", "op-fields"}

    def test_the_overview_light_exposure_and_references_are_on_bottom_cam(self):
        for needed in (
            'id="op-plan-bf-light"',
            'id="op-plan-bf-led"',
            'id="op-plan-bf-exposure"',
            'id="op-bfref-host"',
            'id="op-ov-match"',
        ):
            assert needed in BOTTOM, f"{needed} is not on the Bottom cam pane"
            assert needed not in ACQUIRE, f"{needed} is still on the Acquisition pane"

    def test_acquisition_keeps_the_choice_and_says_where_the_rest_is_set(self):
        for kept in ('id="op-plan-bf"', 'id="op-plan-bf-every"', 'id="op-plan-bf-pos"'):
            assert kept in ACQUIRE
        assert 'id="op-plan-bf-setup"' in ACQUIRE
        assert "data-goto-pane" in OPERATE and "Change on Bottom cam" in OPERATE
        # The old "+ another field, from here" chrome is gone with the select.
        assert "data-bf-pin-add" not in INDEX and "data-bf-pin-add" not in OPERATE

    def test_the_list_is_shared_state_like_the_roster(self):
        assert "overviewFields: []" in STORE_JS
        assert "SharedState.on('overviewFields', render)" in PANEL
        assert "SharedState.on('stageXY', render)" in PANEL
        body = OPERATE[OPERATE.index("function publishFields()") :]
        body = body[: body.index("\n    }")]
        assert "structuredClone(_bfPins)" in body, "a shallow copy is the bug, not the fix"


class TestTheVerbs:
    def test_the_panel_dispatches_rather_than_reimplementing(self):
        assert "OperateManager.fields" in PANEL
        assert "fetch(" not in PANEL, "the fields panel should call verbs, not endpoints"
        exported = OPERATE[OPERATE.index("        fields: {") :]
        exported = exported[: exported.index("\n        }")]
        for verb in ("addHere", "remove", "goTo"):
            assert f"{verb}:" in exported, f"operate.js stopped exporting the {verb} verb"

    def test_a_field_is_made_one_way_from_where_the_stage_is(self):
        fn = OPERATE[OPERATE.index("function addFieldHere()") :]
        fn = fn[: fn.index("\n    }")]
        assert "_bfPins.push({ x: _xy.x, y: _xy.y })" in fn
        assert "No stage position known yet" in fn
        assert "fieldIndexAt(_xy)" in fn, "a field where one already is would be a duplicate frame"
        # The Acquisition select with an empty list goes through the same door.
        wire = OPERATE[OPERATE.index("if (_wired) return;") :]
        wire = wire[: wire.index("\n    async function ")]
        assert "!_bfPins.length && !addFieldHere()" in wire

    def test_going_to_a_field_passes_the_xy_interlock(self):
        fn = OPERATE[OPERATE.index("async function goToField(i)") :]
        fn = fn[: fn.index("\n    }")]
        assert "moveStageTo(" in fn
        assert "/api/devices/stage/move" not in fn

    def test_a_change_is_published_kept_and_said(self):
        fn = OPERATE[OPERATE.index("function fieldsChanged()") :]
        fn = fn[: fn.index("\n    }")]
        for step in ("publishFields();", "persistFields();", "renderPlan();"):
            assert step in fn, step
        assert "pos.value = _bfPins.length ? 'here' : 'centroid'" in fn
        assert "'/api/brightfield/fields'" in OPERATE and "method: 'PUT'" in OPERATE

    def test_the_session_fields_come_back_before_the_last_plan_does(self):
        act = OPERATE[OPERATE.index("async function activate()") :]
        act = act[: act.index("\n    }")]
        assert act.index("await loadFields();") < act.index("await restorePlan();")
        fill = OPERATE[OPERATE.index("function fillPlan(plan)") :][:2600]
        assert "if (!_bfPins.length) {" in fill, (
            "the last run's positions overwrite the session's list"
        )

    def test_the_overview_fields_on_bottom_cam_re_say_the_plan(self):
        wire = OPERATE[OPERATE.index("if (_wired) return;") :]
        wire = wire[: wire.index("\n    async function ")]
        assert "$('op-overview-host')" in wire
        assert "$('op-ov-match')" in wire and "useLiveSettings" in wire
        fn = OPERATE[OPERATE.index("async function useLiveSettings()") :]
        fn = fn[: fn.index("\n    }")]
        assert "/api/devices/camera/exposure" in fn and "light.led === 'Open'" in fn

    def test_the_references_panel_tells_the_plan_when_they_change(self):
        assert "function status()" in REFS and "return { mount, refresh, spec, status };" in REFS
        assert "BrightfieldRefs.mount('op-bfref-host', { onChange: () => renderPlan() })" in OPERATE
        assert "BrightfieldRefs.status()" in OPERATE


class TestTheRailLayout:
    def test_the_two_lists_share_the_rail_and_each_scrolls(self):
        assert ".op-frail-list" in CSS and "max-height" in CSS[CSS.index(".op-frail-list") :][:120]
        # The rail is hidden on Acquisition, which has its own fields mount.
        assert '.op-body[data-pane="acquire"] .op-embryos { display: none; }' in CSS
