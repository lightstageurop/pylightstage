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


def test_sync_client_lifecycle_and_methods():
    """Test that the Sync client correctly spawns a thread and proxies async calls."""

    class FakeWebsocket:
        """A simple fake websocket that safely blocks when iterated over."""

        async def send(self, *args, **kwargs): pass
        async def close(self, *args, **kwargs): pass

        def __aiter__(self):
            async def receiver():
                try:
                    await asyncio.sleep(3600)  # Block forever
                    yield
                except asyncio.CancelledError:
                    pass  # Handle client shutdown cleanly
            return receiver()

    connect_calls = []

    async def fake_connect(uri):
        connect_calls.append(uri)
        return FakeWebsocket()

    with patch("pylightstage.client.websockets.connect", new=fake_connect):
        with LightStageSyncClient("ws://sync_test") as sync_client:
            assert sync_client._thread.is_alive()
            assert sync_client.is_connected
            assert connect_calls == ["ws://sync_test"]

            # Mock the internal send_and_recv on the underlying async client
            sync_client._client._send_and_recv = AsyncMock(
                return_value={"arcs": 10})

            # Call an async method synchronously
            result = sync_client.get_config()
            assert result == {"arcs": 10}

    # Exiting the 'with' block should shut down the thread cleanly
    assert not sync_client._thread.is_alive()
    assert not sync_client.is_connected
