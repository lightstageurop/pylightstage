"""
tests/test_utils.py

Tests the pure data-transformation utilities of the client.
These tests verify that mathematical scaling and dictionary formatting
work correctly before any network requests are built.
"""
import pytest

from pylightstage.client import LightStageClient


pytestmark = pytest.mark.unit


def test_to_16b_scaling():
    """Verify 8-bit float values scale correctly to 16-bit uint (0-65535)."""
    assert LightStageClient._to_16b((0.0, 127.5, 255.0)) == (0, 32767, 65535)

    # Verify clipping bounds
    assert LightStageClient._to_16b((-10.0, 300.0, 255.0)) == (0, 65535, 65535)


def test_build_color_req():
    """Ensure color mode dictionaries include the correct keys."""
    client = LightStageClient()

    # RGB mode
    rgb_res = client._build_color_req('rgb', (255.0, 0.0, 0.0))
    assert 'rgb' in rgb_res and 'white' not in rgb_res
    assert rgb_res['rgb'] == (65535, 0, 0)

    # RGBW mode
    rgbw_res = client._build_color_req('rgbw', (255.0, 255.0, 255.0))
    assert 'rgb' in rgbw_res and 'white' in rgbw_res


def test_unwrap_response():
    """Verify server response envelopes are properly unpacked or turned into errors."""
    client = LightStageClient()

    # Success cases
    assert client._unwrap_response("Ok") is None
    assert client._unwrap_response({"Mode": "Manual"}) == "Manual"
    assert client._unwrap_response({"Config": {"arcs": 6}}) == {"arcs": 6}

    # Server error case
    with pytest.raises(RuntimeError, match=r"Server Error \(404\): Not found"):
        client._unwrap_response(
            {"Error": {"code": 404, "message": "Not found"}})
