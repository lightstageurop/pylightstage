"""
tests/test_sync.py

Tests the synchronous wrapper client.
Verifies that the background event loop thread is spawned, managed,
and shut down safely without hanging the main thread.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

import pytest

from pylightstage.client import LightStageSyncClient

pytestmark = pytest.mark.unit


class FakeWebsocket:
    """A simple fake websocket that safely blocks when iterated over."""

    def __init__(self):
        self.closed = False

    async def send(self, *args, **kwargs):
        pass

    async def close(self, *args, **kwargs):
        self.closed = True

    async def __aiter__(self):
        try:
            await asyncio.Event().wait()  # Block forever
            yield
        except asyncio.CancelledError:
            pass  # Handle client shutdown cleanly


@patch("pylightstage.client.websockets.connect")
def test_sync_client_lifecycle_and_methods(mock_connect):
    """Test that the Sync client correctly spawns a thread and proxies async calls."""
    fake_websocket = FakeWebsocket()

    async def fake_connect(*args, **kwargs):
        return fake_websocket

    mock_connect.side_effect = fake_connect

    with LightStageSyncClient("ws://sync_test") as sync_client:
        # thread lifecycle and connection
        assert sync_client._thread.is_alive()
        assert sync_client.is_connected
        mock_connect.assert_called_once_with("ws://sync_test")

        # Mock the internal send_and_recv on the underlying async client
        sync_client._client._send_and_recv = AsyncMock(return_value={"arcs": 10})

        # Call an async method synchronously
        result = sync_client.get_config()
        assert result == {"arcs": 10}
        sync_client._client._send_and_recv.assert_called_once()

    # Exiting the 'with' block should shut down the thread cleanly
    assert not sync_client._thread.is_alive()
    assert not sync_client.is_connected
    assert fake_websocket.closed


def test_sync_client_stops_its_background_thread_when_connection_fails():
    async def never_connect(_uri):
        await asyncio.sleep(60)

    with patch("pylightstage.client.websockets.connect", new=never_connect):
        sync_client = LightStageSyncClient("ws://unreachable", connect_timeout=0.01)
        with pytest.raises(TimeoutError):
            sync_client.__enter__()

    assert not sync_client._thread.is_alive()


def test_sync_event_callback_can_call_client_method_without_deadlocking():
    sync_client = LightStageSyncClient()
    callback_done = threading.Event()
    callback_results = []
    callback_threads = []
    sync_client._client._send_and_recv = AsyncMock(return_value={"arcs": 12})

    try:

        @sync_client.on_event
        def handle_event(_event):
            callback_threads.append(threading.current_thread())
            callback_results.append(sync_client.get_config())
            callback_done.set()

        registered_callback = sync_client._client._event_callbacks[-1]
        sync_client._loop.call_soon_threadsafe(
            sync_client._client._dispatch_callback,
            registered_callback,
            "ConfigChanged",
        )

        assert callback_done.wait(timeout=1.0)
        assert callback_results == [{"arcs": 12}]
        assert len(callback_threads) == 1
        assert callback_threads[0] is not sync_client._thread
    finally:
        sync_client.close()


def test_sync_client_rejects_blocking_call_from_async_event_callback():
    sync_client = LightStageSyncClient()
    callback_done = threading.Event()
    callback_errors = []
    sync_client._client._send_and_recv = AsyncMock(return_value={"arcs": 12})

    try:

        @sync_client.on_event
        async def handle_event(_event):
            try:
                sync_client.get_config()
            except RuntimeError as exc:
                callback_errors.append(str(exc))
            finally:
                callback_done.set()

        registered_callback = sync_client._client._event_callbacks[-1]
        sync_client._loop.call_soon_threadsafe(
            sync_client._client._dispatch_callback,
            registered_callback,
            "ConfigChanged",
        )

        assert callback_done.wait(timeout=1.0)
        assert callback_errors == [
            "Cannot call a synchronous client method from its event-loop thread."
        ]
    finally:
        sync_client.close()
