"""The device layer stopped and came back; the app must find it again.

`_watch_device_layer` (launch_gently.py) is the one place that connects the
client: when the layer becomes usable it calls `client.connect()` — but only
`if not client.is_connected`. And when the layer goes down it calls
`client.disconnect()`. So the whole reconnect rests on a disconnected client
saying that it is disconnected.

It did not. `disconnect()` closed the session and left the connected flag
set, so a device layer that was stopped and started again (the rig menu's
Stop then Start, or a crash) found the app "attached" with no session: every
hardware route answered 502 with an empty message, and stayed that way until
the app itself was restarted. Found on the simulated rig, 2026-11-13.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from gently.hardware.dispim.client import DiSPIMMicroscope

LAUNCH = (Path(__file__).resolve().parents[1] / "launch_gently.py").read_text(encoding="utf-8")


class _Session:
    closed = False

    async def close(self):
        self.closed = True


def _client() -> DiSPIMMicroscope:
    m = DiSPIMMicroscope.__new__(DiSPIMMicroscope)
    m._session = _Session()
    m._qs_connected = True
    m._sam_available = True
    return m


@pytest.mark.asyncio
async def test_a_disconnected_client_says_it_is_disconnected():
    m = _client()
    session = m._session
    assert m.is_connected is True
    await m.disconnect()
    assert session.closed is True and m._session is None
    assert m.is_connected is False, "the watcher will never reconnect this client"


@pytest.mark.asyncio
async def test_disconnecting_twice_is_harmless():
    m = _client()
    await m.disconnect()
    await m.disconnect()
    assert m.is_connected is False


def test_the_watcher_reconnects_on_what_the_client_reports():
    """The contract the fix restores: both halves read `is_connected`."""
    body = LAUNCH[LAUNCH.index("async def _watch_device_layer(") :]
    body = body[: body.index("\nasync def main(")]
    assert "if client is not None and not client.is_connected:" in body
    assert "await client.connect()" in body
    assert "await client.disconnect()" in body
