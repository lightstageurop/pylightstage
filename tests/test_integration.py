"""
tests/test_integration.py

Integration tests that run against the physical Light Stage server.
If the server is unreachable (e.g., offline or off the VPN), these tests
will automatically skip rather than fail the test suite.
"""
import asyncio
import pytest

from pylightstage.client import LightStageClient


pytestmark = pytest.mark.integration

REAL_SERVER_URI = "ws://127.0.0.1:8080/ws"


@pytest.fixture
async def real_client():
    """
    Attempts to connect to the physical Light Stage.
    Skips the test if the hardware is unreachable within 2 seconds.
    """
    client = LightStageClient(uri=REAL_SERVER_URI)

    try:
        # 2-second timeout prevents tests from hanging if the network is down
        await asyncio.wait_for(client.connect(), timeout=2.0)
    except (asyncio.TimeoutError, OSError, Exception) as e:
        pytest.skip(
            f"Hardware server unreachable at {REAL_SERVER_URI}. Skipping. ({e})"
        )

    yield client

    # Teardown: ensure we disconnect cleanly
    await client.close()


# --- Integration Tests ---

async def test_integration_get_config(real_client):
    """Verify we can fetch and parse the real server's configuration."""
    config = await real_client.get_config()
    assert isinstance(config, dict)


async def test_integration_set_and_read_mode(real_client):
    """Verify we can explicitly set the mode using ModeRequest tagged enums."""
    # original_mode is returned as a StageMode string (e.g. "Demo" or "Manual")
    original_mode = await real_client.get_mode()

    try:
        # 1. Set to Demo mode using internally tagged enum {"type": "Demo"}
        await real_client.set_mode({"type": "Demo"})
        assert await real_client.get_mode() == "Demo"

        # 2. Set to Manual mode using {"type": "Manual"}
        await real_client.set_mode({"type": "Manual"})
        assert await real_client.get_mode() == "Manual"

    finally:
        # Restore the original state using its tagged representation
        if original_mode and real_client.is_connected:
            try:
                await real_client.set_mode({"type": original_mode})
            except Exception:
                pass


async def test_integration_fixture_forces_manual_mode(real_client):
    """
    Verify that sending a fixture update automatically switches the server
    to Manual mode, and that buffered (go=False) updates do not trigger this
    until they are actually flushed.
    """
    original_mode = await real_client.get_mode()
    dim_blue = (0.0, 0.0, 10.0)

    try:
        # 1. Force the server into Demo mode initially
        await real_client.set_mode({"type": "Demo"})
        assert await real_client.get_mode() == "Demo"

        # 2. Buffer a light update without sending it (go=False)
        await real_client.turn_on_light(
            light=1, arc=1, color='rgb', intensity=dim_blue, go=False
        )

        # 3. Verify the mode is STILL Demo (the server hasn't seen the command yet)
        assert await real_client.get_mode() == "Demo"

        # 4. Flush the buffer (go=True)
        await real_client.go()

        # Give the server a fraction of a second to process state change
        await asyncio.sleep(0.1)

        # 5. Verify the server automatically switched to Manual mode
        assert await real_client.get_mode() == "Manual"

        # Clean up the light we just turned on
        await real_client.turn_off_light(light=1, arc=1)

    finally:
        if original_mode and real_client.is_connected:
            try:
                await real_client.set_mode({"type": original_mode})
            except Exception:
                pass


async def test_integration_single_light_cycle(real_client):
    """Verify we can send a SetFixture command without the server rejecting it."""
    dim_white = (10.0, 10.0, 10.0)

    # 1. Turn on light 1 on arc 1
    await real_client.turn_on_light(light=1, arc=1, color='rgbw', intensity=dim_white)
    await asyncio.sleep(0.5)

    # 2. Turn off
    await real_client.turn_off_light(light=1, arc=1)


async def test_integration_batching(real_client):
    """Verify the real server accepts batched SetFixtures commands."""
    dim_red = (10.0, 0.0, 0.0)

    # Queue up two lights
    await real_client.turn_on_light(light=1, arc=1, color='rgb', intensity=dim_red, go=False)
    await real_client.turn_on_light(light=2, arc=1, color='rgb', intensity=dim_red, go=False)

    # Fire the batch
    await real_client.go()
    await asyncio.sleep(0.5)

    # Clean up (turn them off in a batch too)
    await real_client.turn_off_light(light=1, arc=1, go=False)
    await real_client.turn_off_light(light=2, arc=1, go=False)
    await real_client.go()
