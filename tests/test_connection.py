"""
tests/test_connection.py

Tests the WebSocket lifecycle (connecting, disconnecting, and context managers).
We mock the underlying websockets module so these tests run instantly without
requiring the physical hardware.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

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
