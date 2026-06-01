import base64
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates

from gently.ui.web.accounts import AccountStore, set_account_store
from gently.ui.web.auth import Role, SESSION_COOKIE, resolve_role
from gently.ui.web.routes.images import create_router as create_images_router
from gently.ui.web.routes.auth_routes import create_router as create_auth_router
from gently.ui.web.routes.volumes import create_router as create_volumes_router
from gently.ui.web.routes.websocket import _ws_can_control
from gently.ui.web.upload_validation import decode_array_payload


TEMPLATES = Jinja2Templates(
    directory=str(Path(__file__).parents[1] / "gently" / "ui" / "web" / "templates")
)


class _Client:
    def __init__(self, host):
        self.host = host


class _RequestLike:
    def __init__(self, host="192.0.2.10", headers=None, cookies=None):
        self.client = _Client(host)
        self.headers = headers or {}
        self.cookies = cookies or {}


@pytest.fixture(autouse=True)
def _reset_auth(monkeypatch):
    set_account_store(None)
    monkeypatch.delenv("GENTLY_CONTROL_TOKEN", raising=False)
    yield
    set_account_store(None)


def test_legacy_websocket_control_requires_token_for_remote(monkeypatch):
    remote = _RequestLike()
    assert _ws_can_control(remote) is False

    monkeypatch.setenv("GENTLY_CONTROL_TOKEN", "secret")
    with_token = _RequestLike(headers={"X-Gently-Token": "secret"})
    assert _ws_can_control(with_token) is True


def test_legacy_loopback_keeps_control_without_token():
    assert resolve_role(_RequestLike(host="127.0.0.1")) is Role.CONTROL


def test_account_roles_drive_websocket_control(tmp_path):
    store = AccountStore(tmp_path / "auth")
    store.create_user("viewer", "pw", role="viewer")
    store.create_user("operator", "pw", role="operator")
    set_account_store(store)

    viewer = _RequestLike(cookies={SESSION_COOKIE: store.issue_session("viewer")})
    operator = _RequestLike(cookies={SESSION_COOKIE: store.issue_session("operator")})

    assert _ws_can_control(viewer) is False
    assert _ws_can_control(operator) is True


def test_account_store_manages_roles_passwords_and_deletes(tmp_path):
    store = AccountStore(tmp_path / "auth")
    store.create_user("admin", "pw", role="admin")
    store.create_user("viewer", "pw", role="viewer")

    store.set_role("viewer", "operator")
    store.reset_password("viewer", "new-pw")
    assert store.get_role("viewer") == "operator"
    assert store.verify_password("viewer", "new-pw") == "operator"

    store.delete_user("viewer")
    assert store.get_role("viewer") is None

    with pytest.raises(ValueError, match="last admin"):
        store.delete_user("admin")


def test_account_store_rejects_duplicate_users(tmp_path):
    store = AccountStore(tmp_path / "auth")
    store.create_user("admin", "pw", role="admin")

    with pytest.raises(ValueError, match="already exists"):
        store.create_user("admin", "new-pw", role="viewer")

    assert store.verify_password("admin", "pw") == "admin"
    assert store.verify_password("admin", "new-pw") is None


def test_admin_api_lists_updates_and_deletes_users(tmp_path):
    store = AccountStore(tmp_path / "auth")
    store.create_user("admin", "pw", role="admin")
    store.create_user("viewer", "pw", role="viewer")
    set_account_store(store)

    app = FastAPI()
    app.include_router(create_auth_router(SimpleNamespace(templates=None)))
    client = TestClient(app)
    client.cookies.set(SESSION_COOKIE, store.issue_session("admin"))

    resp = client.get("/api/auth/users")
    assert resp.status_code == 200
    assert {u["username"] for u in resp.json()["users"]} == {"admin", "viewer"}

    resp = client.patch(
        "/api/auth/users/viewer",
        json={"role": "operator", "password": "new-pw"},
    )
    assert resp.status_code == 200
    assert store.get_role("viewer") == "operator"
    assert store.verify_password("viewer", "new-pw") == "operator"

    resp = client.delete("/api/auth/users/viewer")
    assert resp.status_code == 200
    assert store.get_role("viewer") is None


def test_admin_users_page_requires_admin_account(tmp_path):
    store = AccountStore(tmp_path / "auth")
    store.create_user("admin", "pw", role="admin")
    store.create_user("viewer", "pw", role="viewer")
    set_account_store(store)

    app = FastAPI()
    app.include_router(create_auth_router(SimpleNamespace(templates=TEMPLATES)))

    anonymous = TestClient(app)
    resp = anonymous.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"

    viewer = TestClient(app)
    viewer.cookies.set(SESSION_COOKIE, store.issue_session("viewer"))
    assert viewer.get("/admin/users").status_code == 403

    admin = TestClient(app)
    admin.cookies.set(SESSION_COOKIE, store.issue_session("admin"))
    resp = admin.get("/admin/users")
    assert resp.status_code == 200
    assert "User accounts" in resp.text
    assert "admin-users-app" in resp.text


def test_image_push_requires_control(monkeypatch):
    app = FastAPI()
    pushed = {}

    async def push_image(array, uid, data_type, metadata):
        pushed["shape"] = array.shape
        pushed["uid"] = uid

    server = SimpleNamespace(push_image=push_image)
    app.include_router(create_images_router(server))
    client = TestClient(app)

    arr = np.array([[1, 2], [3, 4]], dtype=np.uint8)
    payload = {
        "uid": "img-1",
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "image_b64": base64.b64encode(arr.tobytes()).decode("ascii"),
    }

    assert client.post("/api/images", json=payload).status_code == 403

    monkeypatch.setenv("GENTLY_CONTROL_TOKEN", "secret")
    resp = client.post("/api/images", json=payload, headers={"X-Gently-Token": "secret"})
    assert resp.status_code == 200
    assert pushed == {"shape": (2, 2), "uid": "img-1"}


def test_volume_push_requires_control():
    app = FastAPI()
    app.include_router(create_volumes_router(SimpleNamespace()))
    client = TestClient(app)

    assert client.post("/api/volumes3d", json={}).status_code == 403


def test_decode_array_payload_rejects_oversize_shape():
    raw = base64.b64encode(b"\x00").decode("ascii")
    with pytest.raises(HTTPException) as exc:
        decode_array_payload(raw, [8], "uint8", max_nbytes=4, label="image")
    assert exc.value.status_code == 413


def test_decode_array_payload_rejects_shape_mismatch():
    raw = base64.b64encode(b"\x00").decode("ascii")
    with pytest.raises(HTTPException) as exc:
        decode_array_payload(raw, [2], "uint8", max_nbytes=4, label="image")
    assert exc.value.status_code == 400
