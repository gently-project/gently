import pytest


pytestmark = [
    pytest.mark.live_hardware,
    pytest.mark.device_layer,
    pytest.mark.asyncio,
]


async def test_live_device_layer_reports_state(live_hardware_url):
    from gently.hardware.dispim.client import DiSPIMMicroscope

    client = DiSPIMMicroscope(http_url=live_hardware_url)
    try:
        connected = await client.connect()
        assert connected, f"could not connect to device layer at {live_hardware_url}"

        state = await client.get_device_state(refresh=True)

        assert isinstance(state, dict)
        assert state, "device layer returned an empty state payload"
    finally:
        await client.disconnect()
