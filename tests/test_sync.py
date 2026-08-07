"""
tests/test_sync.py

Tests the synchronous wrapper client.
Verifies that the background event loop thread is spawned, managed,
and shut down safely without hanging the main thread.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from pylightstage.client import LightStageSyncClient


pytestmark = pytest.mark.unit


class FakeWebsocket:
    """A simple fake websocket that safely blocks when iterated over."""

    async def send(self, *args, **kwargs):
        pass

    async def close(self, *args, **kwargs):
        pass

    async def __aiter__(self):
        try:
            await asyncio.Event().wait()  # Block forever
            yield
        except asyncio.CancelledError:
            pass  # Handle client shutdown cleanly


@patch("pylightstage.client.websockets.connect")
def test_sync_client_lifecycle_and_methods(mock_connect):
    """Test that the Sync client correctly spawns a thread and proxies async calls."""

    async def fake_connect(*args, **kwargs):
        return FakeWebsocket()

    mock_connect.side_effect = fake_connect

    with LightStageSyncClient("ws://sync_test") as sync_client:
        # thread lifecycle and connection
        assert sync_client._thread.is_alive()
        assert sync_client.is_connected
        mock_connect.assert_called_once_with("ws://sync_test")

        # Mock the internal send_and_recv on the underlying async client
        sync_client._client._send_and_recv = AsyncMock(
            return_value={"arcs": 10})

        # Call an async method synchronously
        result = sync_client.get_config()
        assert result == {"arcs": 10}
        sync_client._client._send_and_recv.assert_called_once()

    # Exiting the 'with' block should shut down the thread cleanly
    assert not sync_client._thread.is_alive()
    assert not sync_client.is_connected


def test_sync_client_stops_its_background_thread_when_connection_fails():
    async def never_connect(_uri):
        await asyncio.sleep(60)

    with patch("pylightstage.client.websockets.connect", new=never_connect):
        sync_client = LightStageSyncClient(
            "ws://unreachable", connect_timeout=0.01
        )
        with pytest.raises(TimeoutError):
            sync_client.__enter__()

    assert not sync_client._thread.is_alive()
