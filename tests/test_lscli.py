"""Unit tests for the atomic pylightstage command-line interface."""

import asyncio
import json
from dataclasses import dataclass
from io import StringIO

import cbor2
import pytest
import websockets

from pylightstage import StageMode
from pylightstage.lscli import DEFAULT_URI, run

pytestmark = pytest.mark.unit


@dataclass
class Summary:
    id: str
    name: str


class FakeClient:
    instances = []

    def __init__(self, *, uri, connect_timeout=5.0):
        self.uri = uri
        self.connect_timeout = connect_timeout
        self.calls = []
        self.closed = False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def set_light(self, **kwargs):
        self.calls.append(("set_light", kwargs))

    def set_pol_light(self, *, arc, light, pol, intensity):
        self.calls.append(
            (
                "set_pol_light",
                {
                    "arc": arc,
                    "light": light,
                    "pol": pol,
                    "intensity": intensity,
                },
            )
        )

    def clear_pol_light(self, *, arc, light, pol):
        self.calls.append(
            (
                "clear_pol_light",
                {
                    "arc": arc,
                    "light": light,
                    "pol": pol,
                },
            )
        )

    def set_mode(self, *args, **kwargs):
        self.calls.append(("set_mode", args, kwargs))

    def trigger(self):
        self.calls.append(("trigger", {}))

    def list_sequences(self):
        self.calls.append(("list_sequences", {}))
        return [Summary(id="01TEST", name="demo")]

    def get_config(self):
        self.calls.append(("get_config", {}))
        return {"arcs": 12}

    def get_mode(self):
        self.calls.append(("get_mode", {}))
        return StageMode.MANUAL


class TtyStringIO(StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def reset_clients():
    FakeClient.instances.clear()


def test_set_light_uses_one_client_call_and_closes_connection():
    status = run(
        [
            "--uri",
            "ws://test/ws",
            "set-light",
            "--arc",
            "2",
            "--light",
            "5",
            "--color",
            "rgb",
            "--intensity",
            "12",
            "34",
            "56",
        ],
        client_factory=FakeClient,
    )

    assert status == 0
    client = FakeClient.instances[0]
    assert client.uri == "ws://test/ws"
    assert client.closed
    assert client.calls == [
        (
            "set_light",
            {
                "arc": 2,
                "light": 5,
                "color": "rgb",
                "intensity": (12.0, 34.0, 56.0),
            },
        )
    ]


def test_clear_polarized_light_uses_polarization_argument():
    run(
        [
            "clear-polarized-light",
            "--arc",
            "1",
            "--light",
            "3",
            "--polarization",
            "cp",
            "--color",
            "w",
        ],
        client_factory=FakeClient,
    )

    assert FakeClient.instances[0].uri == DEFAULT_URI
    assert FakeClient.instances[0].calls == [
        (
            "clear_pol_light",
            {
                "arc": 1,
                "light": 3,
                "pol": "cp",
            },
        )
    ]


def test_set_polarized_light_omits_color_selected_by_client():
    run(
        [
            "set-polarized-light",
            "--arc",
            "2",
            "--light",
            "4",
            "--polarization",
            "pp",
            "--intensity",
            "10",
            "20",
            "30",
        ],
        client_factory=FakeClient,
    )

    assert FakeClient.instances[0].calls == [
        (
            "set_pol_light",
            {
                "arc": 2,
                "light": 4,
                "pol": "pp",
                "intensity": (10.0, 20.0, 30.0),
            },
        )
    ]


def test_capture_modes_require_a_capture_rate_before_connecting():
    with pytest.raises(ValueError, match="--capture-hz"):
        run(["set-mode", "olat"], client_factory=FakeClient)

    assert FakeClient.instances == []


def test_set_olat_mode_passes_capture_configuration():
    run(["set-mode", "olat", "--capture-hz", "24"], client_factory=FakeClient)

    assert FakeClient.instances[0].calls == [
        (
            "set_mode",
            (
                StageMode.OLAT,
                {"capture_hz": 24.0},
            ),
            {},
        )
    ]


def test_set_playback_mode_passes_uploaded_sequence_id():
    run(
        ["set-mode", "playback", "--sequence-id", "01PLAYBACK"],
        client_factory=FakeClient,
    )

    assert FakeClient.instances[0].calls == [
        ("set_mode", (StageMode.PLAYBACK,), {"sequence_id": "01PLAYBACK"})
    ]


@pytest.mark.parametrize("capture_hz", ["0", "-1", "nan", "inf"])
def test_olat_rejects_invalid_capture_rate_before_connecting(capture_hz):
    with pytest.raises(ValueError, match="positive finite"):
        run(
            ["set-mode", "olat", "--capture-hz", capture_hz],
            client_factory=FakeClient,
        )

    assert FakeClient.instances == []


def test_playback_requires_sequence_id_before_connecting():
    with pytest.raises(ValueError, match="--sequence-id"):
        run(["set-mode", "playback"], client_factory=FakeClient)

    assert FakeClient.instances == []


def test_query_results_are_json_encoded():
    output = StringIO()
    run(["list-sequences"], client_factory=FakeClient, stdout=output)

    assert json.loads(output.getvalue()) == [{"id": "01TEST", "name": "demo"}]


def test_no_action_opens_interactive_mode():
    status = run(
        [],
        client_factory=FakeClient,
        stdout=StringIO(),
        stderr=StringIO(),
        input_func=lambda _prompt: "q",
    )

    assert status == 0
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].closed


def test_interactive_pages_clear_the_terminal_before_rendering():
    responses = iter(["1", "b", "q"])
    output = TtyStringIO()

    run(
        [],
        client_factory=FakeClient,
        stdout=output,
        stderr=StringIO(),
        input_func=lambda _prompt: next(responses),
    )

    rendered = output.getvalue()
    assert rendered.count("\033[2J\033[H") == 3
    assert rendered.count("LightStage Interactive Console") == 3


def test_interactive_mode_guides_a_fixture_update_and_closes_cleanly():
    responses = iter(
        [
            "1",  # main: fixtures
            "1",  # fixtures: set one fixture
            "0",
            "1",
            "rgb",
            "255 0 0",  # fixture form
            "",  # continue after successful action
            "b",  # fixture menu: back
            "q",  # main menu: quit
        ]
    )
    output = StringIO()

    status = run(
        ["--uri", "ws://interactive-test/ws", "interactive", "--no-color"],
        client_factory=FakeClient,
        stdout=output,
        stderr=StringIO(),
        input_func=lambda _prompt: next(responses),
    )

    assert status == 0
    client = FakeClient.instances[0]
    assert client.closed
    assert client.uri == "ws://interactive-test/ws"
    assert client.calls == [
        (
            "set_light",
            {
                "arc": 0,
                "light": 1,
                "color": "rgb",
                "intensity": (255.0, 0.0, 0.0),
            },
        )
    ]
    assert "LightStage Interactive Console" in output.getvalue()
    assert "\033[" not in output.getvalue()


def test_interactive_mode_reconnects_when_the_endpoint_changes():
    responses = iter(["5", "ws://replacement/ws", "q"])

    status = run(
        ["interactive", "--no-color"],
        client_factory=FakeClient,
        stdout=StringIO(),
        stderr=StringIO(),
        input_func=lambda _prompt: next(responses),
    )

    assert status == 0
    assert [client.uri for client in FakeClient.instances] == [
        DEFAULT_URI,
        "ws://replacement/ws",
    ]
    assert all(client.closed for client in FakeClient.instances)


def test_interactive_playback_and_manual_trigger_use_server_contract():
    responses = iter(
        [
            "2",  # main: modes and camera
            "5",
            "01PLAYBACK",
            "",  # playback sequence ID, then continue
            "6",
            "",  # manual camera trigger, then continue
            "b",
            "q",
        ]
    )

    status = run(
        ["interactive", "--no-color"],
        client_factory=FakeClient,
        stdout=StringIO(),
        stderr=StringIO(),
        input_func=lambda _prompt: next(responses),
    )

    assert status == 0
    assert FakeClient.instances[0].calls == [
        ("set_mode", (StageMode.PLAYBACK,), {"sequence_id": "01PLAYBACK"}),
        ("trigger", {}),
    ]


def test_interactive_inspection_executes_queries_and_displays_results():
    responses = iter(
        [
            "4",  # main: inspect server
            "1",
            "",  # configuration, then continue
            "2",
            "",  # current mode, then continue
            "3",
            "",  # sequence list, then continue
            "b",
            "q",
        ]
    )
    output = StringIO()

    status = run(
        ["interactive", "--no-color"],
        client_factory=FakeClient,
        stdout=output,
        stderr=StringIO(),
        input_func=lambda _prompt: next(responses),
    )

    assert status == 0
    assert FakeClient.instances[0].calls == [
        ("get_config", {}),
        ("get_mode", {}),
        ("list_sequences", {}),
    ]
    rendered = output.getvalue()
    assert "Running: Show server configuration" in rendered
    assert '"arcs": 12' in rendered
    assert '"Manual"' in rendered
    assert '"name": "demo"' in rendered


async def test_interactive_mode_works_against_a_local_simulated_server():
    received_commands = []

    async def simulated_lsserver(websocket):
        async for payload in websocket:
            request = cbor2.loads(payload)
            received_commands.append(request["command"])
            await websocket.send(
                cbor2.dumps(
                    {
                        "Response": {"id": request["id"], "response": "Ok"},
                    }
                )
            )

    try:
        server = await websockets.serve(simulated_lsserver, "127.0.0.1", 0)
    except OSError as exc:
        pytest.skip(f"Local sockets are unavailable in this environment: {exc}")

    try:
        port = server.sockets[0].getsockname()[1]
        responses = iter(
            [
                "1",
                "1",
                "0",
                "1",
                "rgb",
                "255 0 0",
                "",
                "b",
                "q",
            ]
        )
        status = await asyncio.to_thread(
            run,
            [
                "--uri",
                f"ws://127.0.0.1:{port}",
                "--connect-timeout",
                "1",
                "interactive",
                "--no-color",
            ],
            stdout=StringIO(),
            stderr=StringIO(),
            input_func=lambda _prompt: next(responses),
        )
    finally:
        server.close()
        await server.wait_closed()

    assert status == 0
    assert received_commands == [
        {
            "SetFixture": {
                "arc_idx": 0,
                "light_idx": 1,
                "colour": {"rgb": [65535, 0, 0]},
            },
        }
    ]
