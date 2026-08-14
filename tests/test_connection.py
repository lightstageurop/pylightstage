"""
tests/test_connection.py

Tests the WebSocket lifecycle (connecting, disconnecting, and context managers).
We mock the underlying websockets module so these tests run instantly without
requiring the physical hardware.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from pylightstage.client import LightStageClient

pytestmark = pytest.mark.unit


@patch("pylightstage.client.websockets.connect", new_callable=AsyncMock)
async def test_connect_and_close(mock_connect):
    """Test connecting and cleanly disconnecting the websocket."""
    mock_ws = AsyncMock()
    mock_connect.return_value = mock_ws

    client = LightStageClient("ws://test_uri")
    assert not client.is_connected

    await client.connect()
    assert client.is_connected
    mock_connect.assert_called_once_with("ws://test_uri")
    assert client._receiver_task is not None

    await client.close()
    assert not client.is_connected
    mock_ws.close.assert_called_once()
    assert client._disconnected_event.is_set()


@patch("pylightstage.client.websockets.connect", new_callable=AsyncMock)
async def test_async_context_manager(mock_connect):
    """Test that 'async with' handles connect/close automatically."""
    async with LightStageClient() as client:
        assert client.is_connected
    assert not client.is_connected


async def test_wait_until_disconnected_event():
    """Ensure wait_until_disconnected resolves immediately once close() is called."""
    client = LightStageClient()
    assert not client._disconnected_event.is_set()

    close_task = asyncio.create_task(client.wait_until_disconnected())
    await client.close()

    # Should resolve quickly without timing out
    await asyncio.wait_for(close_task, timeout=1.0)
    assert client._disconnected_event.is_set()


async def test_connect_uses_the_configured_timeout():
    async def never_connect(_uri):
        await asyncio.sleep(60)

    with patch("pylightstage.client.websockets.connect", new=never_connect):
        client = LightStageClient("ws://unreachable", connect_timeout=0.01)
        with pytest.raises(
            TimeoutError,
            match=r"Timed out connecting to ws://unreachable after 0.01 seconds",
        ):
            await client.connect()

    assert not client.is_connected


async def test_send_failure_removes_pending_request():
    client = LightStageClient()
    websocket = AsyncMock()
    websocket.send.side_effect = OSError("send failed")
    client._websocket = websocket

    with pytest.raises(OSError, match="send failed"):
        await client._send_and_recv("GetConfig")

    assert client._pending_requests == {}


async def test_close_failure_still_marks_client_disconnected():
    client = LightStageClient()
    websocket = AsyncMock()
    websocket.close.side_effect = OSError("close failed")
    client._websocket = websocket
    pending = asyncio.get_running_loop().create_future()
    client._pending_requests[1] = pending

    with pytest.raises(OSError, match="close failed"):
        await client.close()

    assert not client.is_connected
    assert client._receiver_task is None
    assert client._disconnected_event.is_set()
    assert client._pending_requests == {}
    with pytest.raises(RuntimeError, match="Connection closed by client"):
        await pending
