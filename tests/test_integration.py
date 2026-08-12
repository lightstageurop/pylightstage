"""
tests/test_integration.py

Integration tests that run against the physical Light Stage server.
If the server is unreachable (e.g., offline or off the VPN), these tests
will automatically skip rather than fail the test suite.
"""

import asyncio

import pytest
import websockets

from pylightstage import LightStageClient, StageMode

pytestmark = pytest.mark.integration

REAL_SERVER_URI = "ws://172.30.40.238:8080/ws"
_RESTORABLE_MODES = frozenset({StageMode.DEMO, StageMode.MANUAL})


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
    except (TimeoutError, OSError, websockets.WebSocketException) as exc:
        pytest.skip(
            f"Hardware server unreachable at {REAL_SERVER_URI}. Skipping. ({exc})"
        )

    yield client

    # Teardown: ensure we disconnect cleanly
    await client.close()


@pytest.fixture
async def restorable_client(real_client):
    """Provide a client whose original mode can be restored exactly."""
    original_mode = await real_client.get_mode()
    if original_mode not in _RESTORABLE_MODES:
        pytest.skip(
            "Mode-changing tests require the stage to begin in Demo or Manual "
            f"mode; {original_mode!r} requires configuration that GetMode does "
            "not expose."
        )

    try:
        yield real_client
    finally:
        if real_client.is_connected:
            await real_client.set_mode(original_mode)


# --- Integration Tests ---


async def test_integration_get_config(real_client):
    """Verify we can fetch and parse the real server's configuration."""
    config = await real_client.get_config()
    assert isinstance(config, dict)


async def test_integration_set_and_read_mode(restorable_client):
    """Verify we can explicitly set the mode using ModeRequest tagged enums."""
    # 1. Set to Demo mode
    await restorable_client.set_mode(StageMode.DEMO)
    assert await restorable_client.get_mode() == StageMode.DEMO

    # 2. Set to Manual mode
    await restorable_client.set_mode("Manual")
    assert await restorable_client.get_mode() == StageMode.MANUAL

    # 3. Set to OLAT
    await restorable_client.set_mode_olat(20.0)
    assert await restorable_client.get_mode() == StageMode.OLAT


async def test_integration_fixture_forces_manual_mode(restorable_client):
    """
    Verify that sending a fixture update automatically switches the server
    to Manual mode, and that buffered (go=False) updates do not trigger this
    until they are actually flushed.
    """
    dim_blue = (0.0, 0.0, 10.0)

    try:
        # 1. Force the server into Demo mode initially
        await restorable_client.set_mode(StageMode.DEMO)
        assert await restorable_client.get_mode() == StageMode.DEMO

        # 2. Buffer a light update without sending it (go=False)
        await restorable_client.turn_on_light(
            light=1, arc=1, color="rgb", intensity=dim_blue, go=False
        )

        # 3. Verify the mode is STILL Demo (the server hasn't seen the command yet)
        assert await restorable_client.get_mode() == StageMode.DEMO

        # 4. Flush the buffer (go=True)
        await restorable_client.go()

        # Give the server a fraction of a second to process state change
        await asyncio.sleep(0.1)

        # 5. Verify the server automatically switched to Manual mode
        assert await restorable_client.get_mode() == StageMode.MANUAL

    finally:
        if restorable_client.is_connected:
            await restorable_client.turn_off_light(light=1, arc=1)


async def test_integration_single_light_cycle(restorable_client):
    """Verify we can send a SetFixture command without the server rejecting it."""
    dim_white = (10.0, 10.0, 10.0)

    try:
        # 1. Turn on light 1 on arc 1
        await restorable_client.turn_on_light(
            light=1, arc=1, color="rgbw", intensity=dim_white
        )
        await asyncio.sleep(0.5)
    finally:
        # 2. Turn off, including when the test body fails.
        if restorable_client.is_connected:
            await restorable_client.turn_off_light(light=1, arc=1)


async def test_integration_batching(restorable_client):
    """Verify the real server accepts batched SetFixtures commands."""
    dim_red = (10.0, 0.0, 0.0)

    try:
        # Queue up two lights
        await restorable_client.turn_on_light(
            light=1, arc=1, color="rgb", intensity=dim_red, go=False
        )
        await restorable_client.turn_on_light(
            light=2, arc=1, color="rgb", intensity=dim_red, go=False
        )

        # Fire the batch
        await restorable_client.go()
        await asyncio.sleep(0.5)
    finally:
        # Clean up in a batch even when the test body fails.
        if restorable_client.is_connected:
            await restorable_client.turn_off_light(light=1, arc=1, go=False)
            await restorable_client.turn_off_light(light=2, arc=1, go=False)
            await restorable_client.go()
