"""Unit tests for the local LightStage web interface framework."""

import http.client
import json
import threading
from io import StringIO

import pytest

from pylightstage.lscli import DEFAULT_URI
from pylightstage.lswebui import DEFAULT_BIND, DEFAULT_PORT, ServerConfig, run
from pylightstage.lswebui.server import _apply_fixture_control, create_server

pytestmark = pytest.mark.unit


class InterruptingServer:
    def __init__(self, config):
        self.config = config
        self.server_address = (config.bind, 45123)
        self.entered = False
        self.closed = False
        self.poll_interval = None

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *_):
        self.closed = True

    def serve_forever(self, poll_interval):
        self.poll_interval = poll_interval
        raise KeyboardInterrupt


def test_command_defaults_match_the_cli_style_and_open_browser():
    servers = []
    opened = []

    def factory(config):
        server = InterruptingServer(config)
        servers.append(server)
        return server

    output = StringIO()
    status = run(
        [], server_factory=factory, browser_opener=opened.append, stdout=output
    )

    assert status == 0
    assert servers[0].config == ServerConfig(
        bind=DEFAULT_BIND,
        port=DEFAULT_PORT,
        lightstage_uri=DEFAULT_URI,
        log_requests=False,
    )
    assert servers[0].entered and servers[0].closed
    assert servers[0].poll_interval == 0.25
    assert opened == ["http://127.0.0.1:45123/"]
    assert "Press Ctrl-C to stop." in output.getvalue()


def test_user_settings_reach_the_server_and_no_browser_is_respected():
    servers = []

    def factory(config):
        server = InterruptingServer(config)
        server.server_address = ("0.0.0.0", 9123)
        servers.append(server)
        return server

    opened = []
    run(
        [
            "--bind",
            "0.0.0.0",
            "--port",
            "9123",
            "--uri",
            "wss://stage.example/ws",
            "--log-requests",
            "--no-browser",
        ],
        server_factory=factory,
        browser_opener=opened.append,
        stdout=StringIO(),
    )

    assert servers[0].config == ServerConfig(
        bind="0.0.0.0",
        port=9123,
        lightstage_uri="wss://stage.example/ws",
        log_requests=True,
    )
    assert opened == []


@pytest.mark.parametrize(
    "config, message",
    [
        (ServerConfig(bind="", port=8000), "bind address"),
        (ServerConfig(port=-1), "port"),
        (ServerConfig(lightstage_uri="http://stage/ws"), "ws:// or wss://"),
    ],
)
def test_invalid_server_configuration_is_rejected(config, message):
    with pytest.raises(ValueError, match=message):
        config.validate()


async def test_fixture_control_uses_the_same_direct_client_operation(monkeypatch):
    actions = []

    class FakeClient:
        def __init__(self, *, uri):
            actions.append(("connect", uri))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def set_light(self, **kwargs):
            actions.append(("set_light", kwargs))

    monkeypatch.setattr("pylightstage.lswebui.server.LightStageClient", FakeClient)
    config = ServerConfig(lightstage_uri="ws://stage.test/ws")

    await _apply_fixture_control(
        config,
        {
            "action": "set",
            "selector": "direct",
            "arc": 2,
            "light": 5,
            "color": "rgbw",
            "intensity": [12, 34, 56],
        },
    )

    assert actions == [
        ("connect", "ws://stage.test/ws"),
        (
            "set_light",
            {
                "light": 5,
                "arc": 2,
                "color": "rgbw",
                "intensity": (12.0, 34.0, 56.0),
            },
        ),
    ]


async def test_fixture_control_supports_polarized_clear(monkeypatch):
    actions = []

    class FakeClient:
        def __init__(self, *, uri):
            self.uri = uri

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def set_pol_light(self, **kwargs):
            actions.append(kwargs)

    monkeypatch.setattr("pylightstage.lswebui.server.LightStageClient", FakeClient)

    await _apply_fixture_control(
        ServerConfig(),
        {
            "action": "clear",
            "selector": "polarized",
            "arc": 1,
            "light": 3,
            "polarization": "cp",
            "intensity": [255, 255, 255],
        },
    )

    assert actions == [
        {
            "light": 3,
            "arc": 1,
            "pol": "cp",
            "intensity": (0.0, 0.0, 0.0),
        }
    ]


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"action": "set", "arc": 12, "light": 0}, "arc index"),
        ({"action": "set", "arc": 0, "light": 14}, "light index"),
        ({"action": "set", "arc": 0, "light": 0, "color": "uv"}, "color value"),
        (
            {
                "action": "set",
                "arc": 0,
                "light": 0,
                "selector": "polarized",
                "polarization": "invalid",
            },
            "polarization",
        ),
    ],
)
async def test_fixture_control_validates_before_connecting(payload, message):
    with pytest.raises((ValueError, IndexError), match=message):
        await _apply_fixture_control(ServerConfig(), payload)


@pytest.fixture
def running_server():
    config = ServerConfig(port=0, lightstage_uri="ws://test-stage:8080/ws")
    try:
        server = create_server(config)
    except OSError as exc:
        pytest.skip(f"Local sockets are unavailable in this environment: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def request(server, method, path):
    connection = http.client.HTTPConnection(
        server.server_address[0], server.server_address[1], timeout=2
    )
    connection.request(method, path)
    response = connection.getresponse()
    body = response.read()
    headers = dict(response.getheaders())
    connection.close()
    return response.status, headers, body


def test_health_and_browser_configuration_endpoints(running_server):
    status, headers, body = request(running_server, "GET", "/api/health")

    assert status == 200
    assert json.loads(body) == {"service": "lswebui", "status": "ok"}
    assert headers["Cache-Control"] == "no-store"
    assert "default-src 'self'" in headers["Content-Security-Policy"]

    status, _, body = request(running_server, "GET", "/api/config")
    config = json.loads(body)
    assert status == 200
    assert config["lightstage_uri"] == "ws://test-stage:8080/ws"
    assert config["webgpu"] == {"fallback": "canvas2d", "preferred": True}
    assert config["features"] == {"fixture_control": True}
    assert "log_requests" not in config


@pytest.mark.parametrize(
    "path, content_type, marker",
    [
        ("/", "text/html", b"stage-view"),
        ("/assets/app.js", "text/javascript", b"WebGPURenderer"),
        ("/assets/renderers/canvas2d.js", "text/javascript", b"honeycomb view"),
        ("/assets/renderers/webgpu.js", "text/javascript", b"vertex_main"),
    ],
)
def test_packaged_web_assets_are_served(running_server, path, content_type, marker):
    status, headers, body = request(running_server, "GET", path)

    assert status == 200
    assert headers["Content-Type"].startswith(content_type)
    assert marker in body


def test_only_allow_listed_assets_are_exposed(running_server):
    status, _, body = request(running_server, "GET", "/assets/../server.py")

    assert status == 404
    assert json.loads(body) == {"error": "Not found"}


def test_head_reports_content_length_without_body(running_server):
    get_status, get_headers, get_body = request(running_server, "GET", "/")
    head_status, head_headers, head_body = request(running_server, "HEAD", "/")

    assert get_status == head_status == 200
    assert head_body == b""
    assert head_headers["Content-Length"] == get_headers["Content-Length"]
    assert int(head_headers["Content-Length"]) == len(get_body)
