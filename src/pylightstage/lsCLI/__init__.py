"""Command-line interface for single LightStage operations.

The public :func:`run` function is also useful when embedding the CLI in another
Python program.  Each call creates a client, performs one action, and closes
the connection before returning.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from enum import Enum
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, Sequence, TextIO

from ..client import LightStageSyncClient
from ..models import PlaybackSequence, StageMode


DEFAULT_URI = "ws://10.37.211.100:8080/ws"
_COLOURS = ("rgb", "w", "rgbw")
_POLARIZATIONS = ("up", "cp", "pp")


def _add_colour_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--color", choices=_COLOURS, default="rgbw",
        help="fixture channel to update (default: rgbw)",
    )


def _add_intensity_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--intensity", nargs=3, type=float, metavar=("RED", "GREEN", "BLUE"),
        default=(255.0, 255.0, 255.0),
        help="three 8-bit channel intensities, each from 0 to 255",
    )


def _add_set_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    *,
    target: str,
    polarized: bool = False,
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(action=name, target=target)
    if target == "light":
        parser.add_argument("--arc", required=True, type=int)
        parser.add_argument("--light", required=True, type=int)
    elif target == "arc":
        parser.add_argument("--arc", required=True, type=int)
    elif target == "horizontal_arc":
        parser.add_argument("--light", required=True, type=int)
    if polarized:
        parser.add_argument("--polarization", choices=_POLARIZATIONS, default="up")
    _add_colour_options(parser)
    _add_intensity_option(parser)


def _add_clear_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
    *,
    target: str,
    polarized: bool = False,
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(action=name, target=target)
    if target == "light":
        parser.add_argument("--arc", required=True, type=int)
        parser.add_argument("--light", required=True, type=int)
    elif target == "arc":
        parser.add_argument("--arc", required=True, type=int)
    elif target == "horizontal_arc":
        parser.add_argument("--light", required=True, type=int)
    if polarized:
        parser.add_argument("--polarization", choices=_POLARIZATIONS, default="up")
    _add_colour_options(parser)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser used by the installed command and ``python -m`` entry point."""
    parser = argparse.ArgumentParser(
        prog="lscli",
        description="Perform one atomic action using the pylightstage interface.",
    )
    parser.add_argument(
        "--uri", default=DEFAULT_URI,
        help=f"LightStage WebSocket endpoint (default: {DEFAULT_URI})",
    )
    parser.add_argument(
        "--connect-timeout", type=float, default=5.0, metavar="SECONDS",
        help="maximum time to wait for the WebSocket connection (default: 5)",
    )
    commands = parser.add_subparsers(dest="action", required=True, title="commands")

    commands.add_parser("get-config", help="print the server configuration")
    commands.add_parser("get-mode", help="print the current stage mode")
    commands.add_parser("trigger", help="trigger a capture in manual mode")
    interactive = commands.add_parser(
        "interactive", aliases=["i"],
        help="open a guided interactive terminal interface",
    )
    interactive.add_argument(
        "--no-color", action="store_true",
        help="disable terminal colours and styling",
    )

    mode = commands.add_parser("set-mode", help="set the stage operation mode")
    mode.add_argument("mode", choices=("demo", "manual", "olat", "playback"))
    mode.add_argument("--capture-hz", type=float, help="required for olat and playback")

    _add_set_command(commands, "set-light", "set one fixture", target="light")
    _add_clear_command(commands, "clear-light", "turn off one fixture", target="light")
    _add_set_command(commands, "set-arc", "set all fixtures in one arc", target="arc")
    _add_clear_command(commands, "clear-arc", "turn off all fixtures in one arc", target="arc")
    _add_set_command(commands, "set-lightstage", "set every fixture", target="lightstage")
    _add_clear_command(commands, "clear-lightstage", "turn off every fixture", target="lightstage")
    _add_set_command(
        commands, "set-horizontal-arc", "set one light index across all arcs",
        target="horizontal_arc",
    )
    _add_clear_command(
        commands, "clear-horizontal-arc", "turn off one light index across all arcs",
        target="horizontal_arc",
    )
    _add_set_command(
        commands, "set-polarized-light", "set one polarized logical fixture",
        target="light", polarized=True,
    )
    _add_clear_command(
        commands, "clear-polarized-light", "turn off one polarized logical fixture",
        target="light", polarized=True,
    )

    commands.add_parser("list-sequences", help="list uploaded playback sequences")
    get_sequence = commands.add_parser("get-sequence", help="print sequence metadata")
    get_sequence.add_argument("sequence_id")
    delete_sequence = commands.add_parser("delete-sequence", help="delete an uploaded sequence")
    delete_sequence.add_argument("sequence_id")
    upload_sequence = commands.add_parser(
        "upload-sequence", help="upload a .cbor or .cbor.zst playback sequence",
    )
    upload_sequence.add_argument("path", type=Path)

    return parser


def _dispatch(client: Any, args: argparse.Namespace) -> Any:
    """Call exactly one synchronous-client method for a parsed command."""
    action = args.action
    if action == "get-config":
        return client.get_config()
    if action == "get-mode":
        return client.get_mode()
    if action == "trigger":
        return client.trigger()
    if action == "set-mode":
        mode = StageMode(args.mode.capitalize() if args.mode != "olat" else "OLAT")
        if mode in (StageMode.OLAT, StageMode.PLAYBACK):
            return client.set_mode(mode, {"capture_hz": args.capture_hz})
        return client.set_mode(mode)

    if action == "list-sequences":
        return client.list_sequences()
    if action == "get-sequence":
        return client.get_sequence(args.sequence_id)
    if action == "delete-sequence":
        return client.delete_sequence(args.sequence_id)
    if action == "upload-sequence":
        return client.upload_sequence(PlaybackSequence.load(args.path))

    method_name = {
        "set-light": "set_light",
        "clear-light": "clear_light",
        "set-arc": "set_arc",
        "clear-arc": "clear_arc",
        "set-lightstage": "set_lightstage",
        "clear-lightstage": "clear_lightstage",
        "set-horizontal-arc": "set_horizontal_arc",
        "clear-horizontal-arc": "clear_horizontal_arc",
        "set-polarized-light": "set_pol_light",
        "clear-polarized-light": "clear_pol_light",
    }.get(action)
    if method_name is None:  # defensive: parser controls all command values
        raise ValueError(f"Unsupported command: {action}")

    kwargs: dict[str, Any] = {"color": args.color}
    if args.target in ("light", "arc"):
        kwargs["arc"] = args.arc
    if args.target in ("light", "horizontal_arc"):
        kwargs["light"] = args.light
    if "polarized" in action:
        kwargs["pol"] = args.polarization
    if action.startswith("set-"):
        kwargs["intensity"] = tuple(args.intensity)
    return getattr(client, method_name)(**kwargs)


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _validate_args(args: argparse.Namespace) -> None:
    """Validate command combinations before opening a network connection."""
    if not math.isfinite(args.connect_timeout) or args.connect_timeout <= 0.0:
        raise ValueError("--connect-timeout must be a positive finite number")
    if args.action != "set-mode":
        return
    needs_capture_hz = args.mode in ("olat", "playback")
    if needs_capture_hz and args.capture_hz is None:
        raise ValueError("--capture-hz is required for olat and playback modes")
    if not needs_capture_hz and args.capture_hz is not None:
        raise ValueError("--capture-hz is only valid for olat and playback modes")


def run(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., Any] = LightStageSyncClient,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    input_func: Callable[[str], str] = input,
) -> int:
    """Run one CLI command and return a shell-style exit status.

    Errors from the client deliberately propagate, allowing callers to choose
    how to present them.  :func:`main` provides the user-facing error handling.
    """
    args = build_parser().parse_args(argv)
    _validate_args(args)
    output = stdout if stdout is not None else sys.stdout
    if args.action in ("interactive", "i"):
        from .interactive import run_interactive

        return run_interactive(
            args.uri,
            client_factory=client_factory,
            connect_timeout=args.connect_timeout,
            dispatch=_dispatch,
            json_default=_json_default,
            stdout=output,
            stderr=stderr,
            input_func=input_func,
            color=False if args.no_color else None,
        )
    with client_factory(uri=args.uri, connect_timeout=args.connect_timeout) as client:
        result = _dispatch(client, args)
    if result is not None:
        print(json.dumps(result, default=_json_default, indent=2, sort_keys=True), file=output)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point."""
    try:
        return run(argv)
    except Exception as exc:
        print(f"lscli: error: {exc}", file=sys.stderr)
        return 1


__all__ = ["DEFAULT_URI", "build_parser", "main", "run"]
