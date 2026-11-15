"""Who can change things: this app's own pages, from the rig PC or with the token.

From an audit. With no accounts, control is granted to the rig PC by its
address. Two ways round that:

- A page of any other site, open in the rig's browser, could send a request
  to ``localhost:8080`` and be obeyed: it comes from the rig PC too.
- The agent's WebSocket granted control to whoever connected, without the
  check the HTTP routes make.
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from gently.ui.web import auth


def test_a_request_says_where_its_page_is_from():
    same = auth.same_origin
    assert same({"host": "localhost:8080", "origin": "http://localhost:8080"})
    assert same({"host": "LocalHost:8080", "origin": "http://localhost:8080"})
    # Not from a page at all: a script, the device layer, curl.
    assert same({"host": "localhost:8080"})
    assert not same({"host": "localhost:8080", "origin": "https://example.org"})
    assert not same({"host": "localhost:8080", "origin": "http://localhost:3000"})
    assert not same({"host": "localhost:8080", "origin": "null"})


def _socket(ip, **headers):
    return SimpleNamespace(client=SimpleNamespace(host=ip), headers=headers)


def test_the_agents_socket_is_driven_from_the_rig_or_with_the_token(monkeypatch):
    monkeypatch.delenv("GENTLY_CONTROL_TOKEN", raising=False)
    may = auth.socket_may_control
    own = {"host": "localhost:8080", "origin": "http://localhost:8080"}
    assert may(_socket("127.0.0.1", **own))
    # Somebody else on the network, watching: it was True for them too.
    assert not may(_socket("10.1.2.3", host="rig:8080", origin="http://rig:8080"))
    # Another site's page, in the rig's own browser.
    assert not may(_socket("127.0.0.1", host="localhost:8080", origin="https://example.org"))

    monkeypatch.setenv("GENTLY_CONTROL_TOKEN", "s3cret")
    remote = {"host": "rig:8080", "origin": "http://rig:8080"}
    assert may(_socket("10.1.2.3", **remote, **{auth._TOKEN_HEADER: "s3cret"}))
    assert not may(_socket("10.1.2.3", **remote, **{auth._TOKEN_HEADER: "wrong"}))


def test_the_socket_and_the_server_use_them():
    from pathlib import Path

    web = Path(auth.__file__).parent
    ws = (web / "routes" / "agent_ws.py").read_text(encoding="utf-8")
    assert "can_control = socket_may_control(websocket)" in ws
    assert "can_control = True" not in ws
    assert "role in CONTROL_ROLES and same_origin(websocket.headers)" in ws
    server = (web / "server.py").read_text(encoding="utf-8")
    assert server.index("async def _own_pages_only(") < server.index("async def _record_actions(")
    campaigns = (web / "routes" / "campaigns.py").read_text(encoding="utf-8")
    for route in (
        '/items/{item_id}/sessions",\n        dependencies=',
        '/items/{item_id}/sessions/{session_id}",\n        dependencies=',
    ):
        assert route in campaigns


def test_a_change_from_another_sites_page_is_refused_before_any_route():
    made = []
    app = FastAPI()

    @app.post("/api/thing")
    async def thing():
        made.append(1)
        return {"ok": True}

    @app.get("/api/thing")
    async def read():
        return {"ok": True}

    # The same middleware the server installs.
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def _own_pages_only(request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and not auth.same_origin(
            request.headers
        ):
            return JSONResponse({"detail": "another site"}, status_code=403)
        return await call_next(request)

    c = TestClient(app)
    assert c.post("/api/thing", headers={"origin": "https://example.org"}).status_code == 403
    assert made == []
    assert c.post("/api/thing").status_code == 200
    assert c.post("/api/thing", headers={"origin": "http://testserver"}).status_code == 200
    # Reading is not changed by this.
    assert c.get("/api/thing", headers={"origin": "https://example.org"}).status_code == 200
