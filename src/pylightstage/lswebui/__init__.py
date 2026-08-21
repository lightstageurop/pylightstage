"""Local web interface and WebGPU visualization host for LightStage.

Like :mod:`pylightstage.lscli`, this module provides an installed command, a
``python -m`` entry point, and importable setup helpers for embedding.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from ..lscli import DEFAULT_URI
from .server import (
    DEFAULT_BIND,
    DEFAULT_PORT,
    LightStageWebServer,
    ServerConfig,
    ServerFactory,
    create_server,
)


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 0 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    """Build the parser used by the installed command and module entry point."""

    parser = argparse.ArgumentParser(
        prog="lswebui",
        description="Start the local LightStage WebGPU interface.",
    )
    parser.add_argument(
        "--bind",
        default=DEFAULT_BIND,
        metavar="ADDRESS",
        help=f"address on which to listen (default: {DEFAULT_BIND})",
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        type=_port,
        metavar="PORT",
        help=f"TCP port; use 0 to choose a free port (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--uri",
        default=DEFAULT_URI,
        metavar="WEBSOCKET_URI",
        help=f"LightStage WebSocket endpoint exposed to the UI (default: {DEFAULT_URI})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open the interface in the default browser",
    )
    parser.add_argument(
        "--log-requests",
        action="store_true",
        help="write HTTP request logs to standard error",
    )
    return parser


def _browser_url(server: LightStageWebServer, configured_bind: str) -> str:
    address = server.server_address
    host = str(address[0])
    port = int(address[1])
    if configured_bind in ("0.0.0.0", "::"):
        host = "127.0.0.1" if configured_bind == "0.0.0.0" else "::1"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}/"


def run(
    argv: Sequence[str] | None = None,
    *,
    server_factory: ServerFactory = create_server,
    browser_opener: Callable[[str], Any] = webbrowser.open,
    stdout: TextIO | None = None,
) -> int:
    """Create and serve the web UI until interrupted.

    ``server_factory`` and ``browser_opener`` are injectable so applications
    can embed the same user setup flow without global monkeypatching.
    """

    args = build_parser().parse_args(argv)
    config = ServerConfig(
        bind=args.bind,
        port=args.port,
        lightstage_uri=args.uri,
        log_requests=args.log_requests,
    )
    config.validate()
    output = stdout if stdout is not None else sys.stdout

    with server_factory(config) as server:
        url = _browser_url(server, config.bind)
        print(f"lswebui serving at {url}", file=output, flush=True)
        print(f"LightStage endpoint: {config.lightstage_uri}", file=output, flush=True)
        print("Press Ctrl-C to stop.", file=output, flush=True)
        if not args.no_browser:
            browser_opener(url)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            print("\nlswebui stopped.", file=output)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point with concise user-facing errors."""

    try:
        return run(argv)
    except Exception as exc:  # noqa: BLE001 - command boundary reports all failures
        print(f"lswebui: error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "DEFAULT_BIND",
    "DEFAULT_PORT",
    "DEFAULT_URI",
    "LightStageWebServer",
    "ServerConfig",
    "build_parser",
    "create_server",
    "main",
    "run",
]
