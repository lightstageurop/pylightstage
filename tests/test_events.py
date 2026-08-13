"""
tests/test_events.py

Tests the asynchronous event listening and dispatching mechanism.
Verifies that blocking methods yield correctly when target events arrive.
"""

import asyncio

import pytest

from pylightstage.client import LightStageClient

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("event_name", "event_payload"),
    [
        ("CaptureFinished", "CaptureFinished"),
        ("ModeChanged", {"ModeChanged": "Playback"}),
    ],
)
async def test_wait_for_server_events(event_name, event_payload):
    """Test the event shapes serialized by the Rust server."""
    client = LightStageClient()

    wait_task = asyncio.create_task(client.wait_for_event(event_name, timeout=1.0))

    # Yield briefly so wait_task can register its callback
    await asyncio.sleep(0.01)

    # Simulate receiving the event from the websocket loop
    for cb in client._event_callbacks:
        cb(event_payload)

    result = await wait_task
    assert result == event_payload


async def test_wait_for_event_timeout():
    """Test wait_for_event raises TimeoutError if the event never arrives."""
    client = LightStageClient()
    with pytest.raises(asyncio.TimeoutError):
        await client.wait_for_event("NeverHappens", timeout=0.1)
