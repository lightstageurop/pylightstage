"""
tests/test_api.py

Tests the high-level API methods (e.g., turn_on_light, get_config).
By mocking `_send_and_recv`, we verify that the client constructs the correct
dictionary payloads and correctly manages batched state, isolating the logic
from the network layer.
"""

from unittest.mock import AsyncMock

import pytest

from pylightstage import CaptureConfig, LightStageClient, StageMode

pytestmark = pytest.mark.unit


async def test_get_config_and_mode():
    """Test configuration getters send correct commands."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(side_effect=[{"arcs": 12}, "Manual"])

    assert await client.get_config() == {"arcs": 12}
    assert await client.get_mode() == StageMode.MANUAL

    calls = client._send_and_recv.call_args_list
    assert calls[0][0][0] == "GetConfig"
    assert calls[1][0][0] == "GetMode"


async def test_set_mode_payloads():
    """Test mode requests are encoded as Rust tagged enum payloads."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.set_mode(StageMode.MANUAL)
    assert client._send_and_recv.call_args[0][0] == {"SetMode": {"type": "Manual"}}

    client._send_and_recv.reset_mock()
    await client.set_mode(StageMode.DEMO)
    assert client._send_and_recv.call_args[0][0] == {"SetMode": {"type": "Demo"}}

    client._send_and_recv.reset_mock()
    await client.set_mode_olat(25.0)
    assert client._send_and_recv.call_args[0][0] == {
        "SetMode": {"type": "OLAT", "config": {"capture_hz": 25.0}}
    }

    client._send_and_recv.reset_mock()
    await client.set_mode_playback("01PLAYBACK")
    assert client._send_and_recv.call_args[0][0] == {
        "SetMode": {"type": "Playback", "id": "01PLAYBACK"}
    }

    client._send_and_recv.reset_mock()
    await client.set_mode(
        {
            "type": StageMode.OLAT,
            "config": CaptureConfig(capture_hz=15.0),
        }
    )
    assert client._send_and_recv.call_args[0][0] == {
        "SetMode": {"type": "OLAT", "config": {"capture_hz": 15.0}}
    }


async def test_camera_trigger_and_sequence_requests_match_server_protocol():
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.trigger()
    client._send_and_recv.assert_awaited_once_with("ManualTrigger")

    client._send_and_recv.reset_mock()
    await client.list_sequences()
    client._send_and_recv.assert_awaited_once_with("ListSequences")

    client._send_and_recv.reset_mock()
    await client.get_sequence("01PLAYBACK")
    client._send_and_recv.assert_awaited_once_with({"GetSequence": "01PLAYBACK"})

    client._send_and_recv.reset_mock()
    await client.delete_sequence("01PLAYBACK")
    client._send_and_recv.assert_awaited_once_with({"DeleteSequence": "01PLAYBACK"})

    client._send_and_recv.reset_mock()
    sequence = {"name": "demo", "capture_hz": 30.0, "frames": []}
    await client.upload_sequence(sequence)
    client._send_and_recv.assert_awaited_once_with(
        {"UploadSequence": sequence}, timeout=60.0
    )


async def test_turn_on_light_immediate():
    """Test setting a single light sends an immediate request if batching is skipped."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_light(light=5, arc=2, color="rgb", intensity=(255, 0, 0))

    client._send_and_recv.assert_called_once()
    cmd = client._send_and_recv.call_args[0][0]

    assert "SetFixture" in cmd
    assert cmd["SetFixture"]["arc_idx"] == 2
    assert cmd["SetFixture"]["light_idx"] == 5
    assert cmd["SetFixture"]["colour"]["rgb"] == (65535, 0, 0)
    assert "white" not in cmd["SetFixture"]["colour"]


async def test_pending_updates_merge_colour_channels():
    """RGB and white updates for one fixture should not overwrite each other."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_light(
        light=1, arc=0, color="rgb", intensity=(255, 0, 0), go=False
    )
    await client.turn_on_light(
        light=1, arc=0, color="w", intensity=(0, 255, 0), go=False
    )
    await client.go()

    fixture = client._send_and_recv.call_args[0][0]["SetFixtures"][0]
    assert fixture["colour"]["rgb"] == (65535, 0, 0)
    assert fixture["colour"]["white"] == (0, 65535, 0)


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

    await client.turn_on_arc(arc=1, color="w", intensity=(0, 0, 255.0))
    cmd = client._send_and_recv.call_args[0][0]
    assert "SetArc" in cmd
    assert cmd["SetArc"]["colour"]["white"] == (0, 0, 65535)

    client._send_and_recv.reset_mock()
    await client.turn_on_lightstage(color="rgbw")
    cmd = client._send_and_recv.call_args[0][0]
    assert "SetLightstage" in cmd


async def test_polarized_light_routes_to_expected_fixture_type():
    """Polarization modes choose the RGB or white fixture for each logical light."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_pol_light(light=0, arc=0, pol="pp", intensity=(255, 0, 0))
    cmd = client._send_and_recv.call_args[0][0]
    assert "rgb" in cmd["SetFixture"]["colour"]
    assert "white" not in cmd["SetFixture"]["colour"]

    client._send_and_recv.reset_mock()
    await client.turn_on_pol_light(light=0, arc=0, pol="cp", intensity=(255, 0, 0))
    cmd = client._send_and_recv.call_args[0][0]
    assert "white" in cmd["SetFixture"]["colour"]
    assert "rgb" not in cmd["SetFixture"]["colour"]


class EnvMap(list):
    shape = (168, 3)


async def test_show_env_map_batches_all_fixtures():
    """Environment maps are sent as one batched update in legacy arc-major order."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)
    env_map = EnvMap([[1, 2, 3] for _ in range(168)])

    await client.show_env_map(env_map, color="rgb", scale=0.5)

    cmd = client._send_and_recv.call_args[0][0]
    fixtures = cmd["SetFixtures"]
    assert len(fixtures) == 168
    assert fixtures[0]["arc_idx"] == 0
    assert fixtures[0]["light_idx"] == 0
    assert fixtures[14]["arc_idx"] == 1
    assert fixtures[14]["light_idx"] == 0
    assert fixtures[0]["colour"]["rgb"] == (128, 257, 385)


async def test_show_pol_env_map_new_can_limit_to_rgb_or_white():
    """The newer polarized helper can send only the selected fixture family."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)
    env_map = EnvMap([[255, 255, 255] for _ in range(168)])

    await client.show_pol_env_map(env_map, pol="pp", color="rgb")

    fixtures = client._send_and_recv.call_args[0][0]["SetFixtures"]
    assert len(fixtures) == 84
    assert all("rgb" in fixture["colour"] for fixture in fixtures)
    assert all("white" not in fixture["colour"] for fixture in fixtures)


async def test_turn_on_horizontal_arc_batches_light_index_across_arcs():
    """The legacy horizontal arc helper means one light index across every arc."""
    client = LightStageClient()
    client._send_and_recv = AsyncMock(return_value=None)

    await client.turn_on_horizontal_arc(3, color="w", intensity=(0, 0, 255))

    fixtures = client._send_and_recv.call_args[0][0]["SetFixtures"]
    assert len(fixtures) == 12
    assert {fixture["arc_idx"] for fixture in fixtures} == set(range(12))
    assert {fixture["light_idx"] for fixture in fixtures} == {3}
    assert all("white" in fixture["colour"] for fixture in fixtures)
