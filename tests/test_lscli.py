"""Unit tests for the atomic pylightstage command-line interface."""

from dataclasses import dataclass
from io import StringIO
import json

import pytest

from pylightstage import StageMode
from pylightstage.lsCLI import DEFAULT_URI, run


pytestmark = pytest.mark.unit


@dataclass
class Summary:
    id: str
    name: str


class FakeClient:
    instances = []

    def __init__(self, *, uri):
        self.uri = uri
        self.calls = []
        self.closed = False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def set_light(self, **kwargs):
        self.calls.append(("set_light", kwargs))

    def clear_pol_light(self, **kwargs):
        self.calls.append(("clear_pol_light", kwargs))

    def set_mode(self, *args):
        self.calls.append(("set_mode", args))

    def list_sequences(self):
        self.calls.append(("list_sequences", {}))
        return [Summary(id="01TEST", name="demo")]


@pytest.fixture(autouse=True)
def reset_clients():
    FakeClient.instances.clear()


def test_set_light_uses_one_client_call_and_closes_connection():
    status = run(
        ["--uri", "ws://test/ws", "set-light", "--arc", "2", "--light", "5",
         "--color", "rgb", "--intensity", "12", "34", "56"],
        client_factory=FakeClient,
    )

    assert status == 0
    client = FakeClient.instances[0]
    assert client.uri == "ws://test/ws"
    assert client.closed
    assert client.calls == [("set_light", {
        "arc": 2, "light": 5, "color": "rgb", "intensity": (12.0, 34.0, 56.0),
    })]


def test_clear_polarized_light_uses_polarization_argument():
    run(
        ["clear-polarized-light", "--arc", "1", "--light", "3",
         "--polarization", "cp", "--color", "w"],
        client_factory=FakeClient,
    )

    assert FakeClient.instances[0].uri == DEFAULT_URI
    assert FakeClient.instances[0].calls == [("clear_pol_light", {
        "arc": 1, "light": 3, "color": "w", "pol": "cp",
    })]


def test_capture_modes_require_a_capture_rate_before_connecting():
    with pytest.raises(ValueError, match="--capture-hz"):
        run(["set-mode", "olat"], client_factory=FakeClient)

    assert FakeClient.instances == []


def test_set_mode_passes_capture_configuration():
    run(["set-mode", "playback", "--capture-hz", "24"], client_factory=FakeClient)

    assert FakeClient.instances[0].calls == [("set_mode", (
        StageMode.PLAYBACK, {"capture_hz": 24.0},
    ))]


def test_query_results_are_json_encoded():
    output = StringIO()
    run(["list-sequences"], client_factory=FakeClient, stdout=output)

    assert json.loads(output.getvalue()) == [{"id": "01TEST", "name": "demo"}]
