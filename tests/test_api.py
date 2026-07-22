"""
tests/test_api.py

Tests the high-level API methods (e.g., turn_on_light, get_config).
By mocking `_send_and_recv`, we verify that the client constructs the correct 
dictionary payloads and correctly manages batched state, isolating the logic 
from the network layer.
"""
import pytest
from unittest.mock import AsyncMock

from pylightstage.client import LightStageClient


pytestmark = pytest.mark.unit


async def test_get_config_and_mode():
    """Test configuration getters send correct commands."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(side_effect=[{"arcs": 12}, "Manual"])

    assert await client.get_config() == {"arcs": 12}
    assert await client.get_mode() == "Manual"

    calls = client._send_and_recv.call_args_list
    assert calls[0][0][0] == "GetConfig"
    assert calls[1][0][0] == "GetMode"


async def test_turn_on_light_immediate():
    """Test setting a single light sends an immediate request if batching is skipped."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_light(light=5, arc=2, color='rgb', intensity=(255, 0, 0))

    client._send_and_recv.assert_called_once()
    cmd = client._send_and_recv.call_args[0][0]

    assert "SetFixture" in cmd
    assert cmd["SetFixture"]["arc_idx"] == 2
    assert cmd["SetFixture"]["light_idx"] == 5
    assert cmd["SetFixture"]["colour"]["rgb"] == (65535, 0, 0)
    assert "white" not in cmd["SetFixture"]["colour"]


async def test_batching_updates_with_go():
    """Verify that go=False buffers light updates until go() is explicitly called."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_light(light=1, arc=0, intensity=(255, 0, 0), go=False)
    await client.turn_on_light(light=2, arc=0, intensity=(0, 255, 0), go=False)

    assert len(client._pending_updates) == 2
    client._send_and_recv.assert_not_called()

    await client.go()
    assert len(client._pending_updates) == 0
    client._send_and_recv.assert_called_once()

    cmd = client._send_and_recv.call_args[0][0]
    assert "SetFixtures" in cmd
    assert len(cmd["SetFixtures"]) == 2


async def test_arc_and_lightstage_commands():
    """Test arc and global lightstage setter payloads."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_arc(arc=1, color='w', intensity=(0, 0, 255.0))
    cmd = client._send_and_recv.call_args[0][0]
    assert "SetArc" in cmd
    assert cmd["SetArc"]["colour"]["white"] == (0, 0, 65535)

    client._send_and_recv.reset_mock()
    await client.turn_on_lightstage(color='rgbw')
    cmd = client._send_and_recv.call_args[0][0]
    assert "SetLightstage" in cmd
