"""HTTP server primitives for the local LightStage web interface."""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from ..client import LightStageClient
from ..lscli import DEFAULT_URI
from ..models import ColorMode, PolarizationMode
from ..utils import color_mode, polarization_mode, validate_index, validate_intensity

DEFAULT_BIND = "127.0.0.1"
DEFAULT_PORT = 8000
_MAX_REQUEST_BYTES = 32_768
_JSON_TYPE = "application/json; charset=utf-8"
_CSP = (
    "default-src 'self'; connect-src 'self' ws: wss:; "
    "img-src 'self' data:; script-src 'self'; style-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Content-Security-Policy": _CSP,
}

_INSPECT_ACTIONS = {
    "get-config": "get_config",
    "get-mode": "get_mode",
    "list-sequences": "list_sequences",
}
_CONTROL_TARGETS = ("fixture", "arc", "horizontal_arc")
_NUM_ARCS = 12
_LIGHTS_PER_ARC = 14


@dataclass(frozen=True, slots=True)
class ServerConfig:
    """Settings shared by the HTTP server and browser application."""

    bind: str = DEFAULT_BIND
    port: int = DEFAULT_PORT
    lightstage_uri: str = DEFAULT_URI
    log_requests: bool = False

    def validate(self) -> None:
        if not self.bind:
            raise ValueError("bind address must not be empty")
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if not self.lightstage_uri.startswith(("ws://", "wss://")):
            raise ValueError("LightStage URI must use ws:// or wss://")


_STATIC_FILES: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/assets/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/assets/api.js": ("api.js", "text/javascript; charset=utf-8"),
    "/assets/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/assets/camera.js": ("camera.js", "text/javascript; charset=utf-8"),
    "/assets/dom.js": ("dom.js", "text/javascript; charset=utf-8"),
    "/assets/fixture-controls.js": (
        "fixture-controls.js",
        "text/javascript; charset=utf-8",
    ),
    "/assets/math.js": ("math.js", "text/javascript; charset=utf-8"),
    "/assets/scene.js": ("scene.js", "text/javascript; charset=utf-8"),
    "/assets/renderers/canvas2d.js": (
        "renderers/canvas2d.js",
        "text/javascript; charset=utf-8",
    ),
    "/assets/renderers/webgpu.js": (
        "renderers/webgpu.js",
        "text/javascript; charset=utf-8",
    ),
}


def _required_index(payload: dict[str, Any], name: str, size: int) -> int:
    value = payload.get(name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{name} must be an integer")
    return validate_index(name, value, size=size)


def _control_target(payload: dict[str, Any]) -> tuple[str, int | None, int | None]:
    target = payload.get("target", "fixture")
    if target not in _CONTROL_TARGETS:
        choices = ", ".join(repr(choice) for choice in _CONTROL_TARGETS)
        raise ValueError(f"target must be one of: {choices}")
    arc = (
        _required_index(payload, "arc", _NUM_ARCS)
        if target in ("fixture", "arc")
        else None
    )
    light = (
        _required_index(payload, "light", _LIGHTS_PER_ARC)
        if target in ("fixture", "horizontal_arc")
        else None
    )
    return target, arc, light


def _control_targets(
    payload: dict[str, Any],
) -> list[tuple[str, int | None, int | None]]:
    raw_targets = payload.get("targets")
    if raw_targets is None:
        return [_control_target(payload)]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise TypeError("targets must be a non-empty array")

    targets: list[tuple[str, int | None, int | None]] = []
    for raw_target in raw_targets:
        if not isinstance(raw_target, dict):
            raise TypeError("each target must be a JSON object")
        target = _control_target(raw_target)
        if target not in targets:
            targets.append(target)
    return targets


async def _apply_fixture_control(config: ServerConfig, payload: dict[str, Any]) -> None:
    """Apply one explicit fixture or fixture-group action through the client API."""

    action = payload.get("action")
    if action not in ("set", "clear"):
        raise ValueError("action must be 'set' or 'clear'")
    targets = _control_targets(payload)
    intensity = validate_intensity(
        [0, 0, 0] if action == "clear" else payload.get("intensity", [255, 255, 255])
    )

    selector = payload.get("selector", "direct")
    color: ColorMode | None = None
    polarization: PolarizationMode | None = None
    if selector == "direct":
        color = color_mode(payload.get("color", "rgbw"))
    elif selector == "polarized":
        polarization = polarization_mode(payload.get("polarization", "up"))
    else:
        raise ValueError("selector must be 'direct' or 'polarized'")

    async with LightStageClient(uri=config.lightstage_uri) as client:
        if color is not None:
            for target, arc, light in targets:
                if target == "fixture":
                    assert arc is not None and light is not None
                    await client.set_light(
                        light=light,
                        arc=arc,
                        color=color,
                        intensity=intensity,
                    )
                elif target == "arc":
                    assert arc is not None
                    await client.set_arc(arc=arc, color=color, intensity=intensity)
                else:
                    assert light is not None
                    await client.set_horizontal_arc(
                        light=light,
                        color=color,
                        intensity=intensity,
                    )
        else:
            assert polarization is not None
            fixtures: set[tuple[int, int]] = set()
            for target, arc, light in targets:
                if target == "fixture":
                    assert arc is not None and light is not None
                    fixtures.add((arc, light))
                elif target == "arc":
                    assert arc is not None
                    fixtures.update(
                        (arc, light_index) for light_index in range(_LIGHTS_PER_ARC)
                    )
                else:
                    assert light is not None
                    fixtures.update(
                        (arc_index, light) for arc_index in range(_NUM_ARCS)
                    )

            if len(fixtures) == 1:
                arc, light = fixtures.pop()
                await client.set_pol_light(
                    light=light,
                    arc=arc,
                    pol=polarization,
                    intensity=intensity,
                )
            else:
                for arc_index, light_index in sorted(fixtures):
                    await client.set_pol_light(
                        light=light_index,
                        arc=arc_index,
                        pol=polarization,
                        intensity=intensity,
                        go=False,
                    )
                await client.go()


def _control_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Return target-aware metadata while preserving the original fixture response."""

    if "targets" in payload:
        return {
            "status": "ok",
            "targets": payload["targets"],
            "action": payload["action"],
        }
    if "target" not in payload:
        return {
            "status": "ok",
            "arc": payload["arc"],
            "light": payload["light"],
            "action": payload["action"],
        }

    target = payload["target"]
    response = {"status": "ok", "target": target, "action": payload["action"]}
    if target in ("fixture", "arc"):
        response["arc"] = payload["arc"]
    if target in ("fixture", "horizontal_arc"):
        response["light"] = payload["light"]
    return response


async def _inspect_server(config: ServerConfig, action: str) -> Any:
    """Run one read-only action from lscli's Inspect Server submenu."""

    method_name = _INSPECT_ACTIONS.get(action)
    if method_name is None:
        choices = ", ".join(sorted(_INSPECT_ACTIONS))
        raise ValueError(f"action must be one of: {choices}")
    async with LightStageClient(uri=config.lightstage_uri) as client:
        return await getattr(client, method_name)()


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _browser_config(config: ServerConfig) -> dict[str, object]:
    return {
        "bind": config.bind,
        "port": config.port,
        "lightstage_uri": config.lightstage_uri,
        "webgpu": {"preferred": True, "fallback": "canvas2d"},
        "features": {"fixture_control": True},
    }


def _stage_error(
    exc: Exception, config: ServerConfig, operation: str
) -> tuple[HTTPStatus, str]:
    """Map client, validation, and protocol failures to the public HTTP API."""

    if isinstance(exc, (ValueError, IndexError, TypeError)):
        return HTTPStatus.BAD_REQUEST, str(exc)
    if isinstance(exc, TimeoutError):
        return (
            HTTPStatus.GATEWAY_TIMEOUT,
            str(exc) or f"Timed out connecting to {config.lightstage_uri}",
        )
    if isinstance(exc, OSError):
        return (
            HTTPStatus.BAD_GATEWAY,
            f"Could not connect to {config.lightstage_uri}: {exc}",
        )
    if operation == "command" and isinstance(exc, RuntimeError):
        return HTTPStatus.BAD_GATEWAY, f"LightStage protocol error: {exc}"
    detail = exc or "no details provided"
    return (
        HTTPStatus.BAD_GATEWAY,
        (
            f"LightStage {operation} failed at {config.lightstage_uri}: "
            f"{type(exc).__name__}: {detail}"
        ),
    )


class LightStageWebServer(ThreadingHTTPServer):
    """Thread-per-request server with prompt process shutdown semantics."""

    allow_reuse_address = True
    daemon_threads = True
    block_on_close = False


def _handler_for(config: ServerConfig) -> type[BaseHTTPRequestHandler]:
    static_root = files("pylightstage.lswebui").joinpath("static")

    class WebUIRequestHandler(BaseHTTPRequestHandler):
        server_version = "pylightstage-lswebui"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._handle(head_only=False)

        def do_HEAD(self) -> None:
            self._handle(head_only=True)

        def do_POST(self) -> None:
            path = unquote(urlsplit(self.path).path)
            if path != "/api/fixture":
                self._send_error(HTTPStatus.METHOD_NOT_ALLOWED, "Method not allowed")
                return
            try:
                payload = self._read_json_object()
                asyncio.run(_apply_fixture_control(config, payload))
            except Exception as exc:  # noqa: BLE001
                self._send_stage_error(exc, "command")
                return
            self._send_json(_control_response(payload), head_only=False)

        def _read_json_object(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", ""))
            if not 0 < content_length <= _MAX_REQUEST_BYTES:
                raise ValueError("request body must contain JSON")
            payload = json.loads(self.rfile.read(content_length))
            if not isinstance(payload, dict):
                raise TypeError("request body must be a JSON object")
            return payload

        def _handle(self, *, head_only: bool) -> None:
            request_url = urlsplit(self.path)
            path = unquote(request_url.path)
            if path == "/api/health":
                self._send_json(
                    {"service": "lswebui", "status": "ok"}, head_only=head_only
                )
                return
            if path == "/api/config":
                self._send_json(_browser_config(config), head_only=head_only)
                return
            if path == "/api/inspect":
                action = parse_qs(request_url.query).get("action", [""])[0]
                try:
                    result = asyncio.run(_inspect_server(config, action))
                except Exception as exc:  # noqa: BLE001
                    self._send_stage_error(exc, "query", head_only=head_only)
                    return
                self._send_json(
                    {"action": action, "result": result}, head_only=head_only
                )
                return

            asset = _STATIC_FILES.get(path)
            if asset is None:
                self._send_error(HTTPStatus.NOT_FOUND, "Not found", head_only=head_only)
                return
            relative_path, content_type = asset
            try:
                body = static_root.joinpath(*relative_path.split("/")).read_bytes()
            except (FileNotFoundError, OSError):
                self._send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "Packaged web asset is unavailable",
                    head_only=head_only,
                )
                return
            self._send(HTTPStatus.OK, body, content_type, head_only=head_only)

        def _send_json(self, value: object, *, head_only: bool) -> None:
            self._send(
                HTTPStatus.OK,
                _json_bytes(value),
                _JSON_TYPE,
                head_only=head_only,
                cache_control="no-store",
            )

        def _send_stage_error(
            self,
            exc: Exception,
            operation: str,
            *,
            head_only: bool = False,
        ) -> None:
            status, message = _stage_error(exc, config, operation)
            self._send_error(status, message, head_only=head_only)

        def _send_error(
            self,
            status: HTTPStatus,
            message: str,
            *,
            head_only: bool = False,
        ) -> None:
            self._send(
                status,
                _json_bytes({"error": message}),
                _JSON_TYPE,
                head_only=head_only,
                cache_control="no-store",
            )

        def _send(
            self,
            status: HTTPStatus,
            body: bytes,
            content_type: str,
            *,
            head_only: bool,
            cache_control: str = "no-cache",
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            for name, value in _SECURITY_HEADERS.items():
                self.send_header(name, value)
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            if config.log_requests:
                super().log_message(format, *args)

    return WebUIRequestHandler


def create_server(config: ServerConfig) -> LightStageWebServer:
    """Create, bind, and return a configured local web server.

    A port of ``0`` asks the operating system to select an unused port, which
    is especially useful when embedding the UI or running tests.
    """

    config.validate()
    address_family = _address_family(config.bind, config.port)
    server_type = type(
        "ConfiguredLightStageWebServer",
        (LightStageWebServer,),
        {"address_family": address_family},
    )
    return server_type((config.bind, config.port), _handler_for(config))


def _address_family(bind: str, port: int) -> socket.AddressFamily:
    """Choose a socket family while retaining host-name support."""

    flags = socket.AI_PASSIVE if bind in ("0.0.0.0", "::") else 0
    addresses = socket.getaddrinfo(bind, port, type=socket.SOCK_STREAM, flags=flags)
    if not addresses:
        raise OSError(f"could not resolve bind address {bind!r}")
    if ":" in bind:
        for family, *_ in addresses:
            if family == socket.AF_INET6:
                return socket.AF_INET6
    for family, *_ in addresses:
        if family == socket.AF_INET:
            return socket.AF_INET
    return addresses[0][0]


ServerFactory = Callable[[ServerConfig], LightStageWebServer]


__all__ = [
    "DEFAULT_BIND",
    "DEFAULT_PORT",
    "LightStageWebServer",
    "ServerConfig",
    "ServerFactory",
    "create_server",
]
