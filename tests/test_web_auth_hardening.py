import base64
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from gently.ui.web.accounts import AccountStore, set_account_store
from gently.ui.web.auth import Role, SESSION_COOKIE, resolve_role
from gently.ui.web.routes.images import create_router as create_images_router
from gently.ui.web.routes.volumes import create_router as create_volumes_router
from gently.ui.web.routes.websocket import _ws_can_control
from gently.ui.web.upload_validation import decode_array_payload


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
