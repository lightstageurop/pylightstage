"""Command-line interface for LightStage operations.

The public :func:`run` function is also useful when embedding the CLI in another
Python program.  With no action, it starts the interactive console; explicit
actions create a client, perform one operation, and close the connection.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from ..client import LightStageSyncClient
from ..models import PlaybackSequence, StageMode

DEFAULT_URI = "ws://172.30.40.238:8080/ws"
_COLOURS = ("rgb", "w", "rgbw")
_POLARIZATIONS = ("up", "cp", "pp")


_FIXTURE_METHODS = {
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
}

# fmt: off
_FIXTURE_COMMANDS_SPEC = (
    ("set-light", "set one fixture", "light", False, True),
    ("clear-light", "turn off one fixture", "light", False, False),
    ("set-arc", "set all fixtures in one arc", "arc", False, True),
    ("clear-arc", "turn off all fixtures in one arc", "arc", False, False),
    ("set-lightstage", "set every fixture", "lightstage", False, True),
    ("clear-lightstage", "turn off every fixture", "lightstage", False, False),
    ("set-horizontal-arc", "set one light index across all arcs", "horizontal_arc", False, True),
    ("clear-horizontal-arc", "turn off one light index across all arcs", "horizontal_arc", False, False),
    ("set-polarized-light", "set one polarized logical fixture", "light", True, True),
    ("clear-polarized-light", "turn off one polarized logical fixture", "light", True, False),
)
# fmt: on


def _add_colour_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--color",
        choices=_COLOURS,
        default="rgbw",
        help="fixture channel to update (default: rgbw)",
    )


def _add_intensity_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--intensity",
        nargs=3,
        type=float,
        metavar=("RED", "GREEN", "BLUE"),
        default=(255.0, 255.0, 255.0),
        help="three 8-bit channel intensities, each from 0 to 255",
    )


def _add_fixture_command(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    name: str,
    help_text: str,
    *,
    target: str,
    polarized: bool = False,
    is_set: bool = True,
) -> None:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(action=name, target=target)
    if target in ("light", "arc"):
        parser.add_argument("--arc", required=True, type=int)
    if target in ("light", "horizontal_arc"):
        parser.add_argument("--light", required=True, type=int)

    if polarized:
        parser.add_argument("--polarization", choices=_POLARIZATIONS, default="up")
        parser.add_argument("--color", choices=_COLOURS, help=argparse.SUPPRESS)
    else:
        _add_colour_options(parser)

    if is_set:
        _add_intensity_option(parser)


def build_parser() -> argparse.ArgumentParser:
    """Build the parser used by the installed command and ``python -m`` entry point."""
    parser = argparse.ArgumentParser(
        prog="lscli",
        description="Control a LightStage interactively or perform one atomic action.",
    )
    parser.add_argument(
        "--uri",
        default=DEFAULT_URI,
        help=f"LightStage WebSocket endpoint (default: {DEFAULT_URI})",
    )
    parser.add_argument(
        "--connect-timeout",
        type=float,
        default=5.0,
        metavar="SECONDS",
        help="maximum time to wait for the WebSocket connection (default: 5)",
    )
    parser.set_defaults(no_color=False)
    commands = parser.add_subparsers(dest="action", title="commands")

    # simple queries without arguments
    for cmd, help_txt in (
        ("get-config", "print the server configuration"),
        ("get-mode", "print the current stage mode"),
        ("trigger", "trigger a capture in manual mode"),
        ("list-sequences", "list uploaded playback sequences"),
    ):
        commands.add_parser(cmd, help=help_txt)

    interactive = commands.add_parser(
        "interactive",
        aliases=["i"],
        help="open a guided interactive terminal interface",
    )
    interactive.add_argument(
        "--no-color",
        action="store_true",
        help="disable terminal colours and styling",
    )

    mode = commands.add_parser("set-mode", help="set the stage operation mode")
    mode.add_argument("mode", choices=("demo", "manual", "olat", "playback"))
    mode.add_argument("--capture-hz", type=float, help="required for olat")
    mode.add_argument(
        "--sequence-id", help="ID of an uploaded sequence; required for playback"
    )

    # manual mode fixture commands
    for cmd, help_text, target, pol, is_set in _FIXTURE_COMMANDS_SPEC:
        _add_fixture_command(
            commands,
            cmd,
            help_text=help_text,
            target=target,
            polarized=pol,
            is_set=is_set,
        )

    # sequence commands
    for cmd, help_text, arg_name, arg_type in (
        ("get-sequence", "print sequence metadata", "sequence_id", str),
        ("delete-sequence", "delete an uploaded sequence", "sequence_id", str),
        (
            "upload-sequence",
            "upload a .cbor or .cbor.zst playback sequence",
            "path",
            Path,
        ),
    ):
        p = commands.add_parser(cmd, help=help_text)
        p.add_argument(arg_name, type=arg_type)

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
        if mode == StageMode.OLAT:
            return client.set_mode(mode, {"capture_hz": args.capture_hz})
        if mode == StageMode.PLAYBACK:
            return client.set_mode(mode, sequence_id=args.sequence_id)
        return client.set_mode(mode)

    if action == "list-sequences":
        return client.list_sequences()
    if action == "get-sequence":
        return client.get_sequence(args.sequence_id)
    if action == "delete-sequence":
        return client.delete_sequence(args.sequence_id)
    if action == "upload-sequence":
        return client.upload_sequence(PlaybackSequence.load(args.path))

    method_name = _FIXTURE_METHODS.get(action)
    if method_name is None:  # defensive: parser controls all command values
        raise ValueError(f"Unsupported command: {action}")

    polarized = "polarized" in action
    kwargs: dict[str, Any] = {}
    if not polarized:
        kwargs["color"] = args.color
    if args.target in ("light", "arc"):
        kwargs["arc"] = args.arc
    if args.target in ("light", "horizontal_arc"):
        kwargs["light"] = args.light
    if polarized:
        kwargs["pol"] = args.polarization
    if action.startswith("set-"):
        kwargs["intensity"] = tuple(args.intensity)
    return getattr(client, method_name)(**kwargs)


def _json_default(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
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
    if args.capture_hz is not None and (
        not math.isfinite(args.capture_hz) or args.capture_hz <= 0.0
    ):
        raise ValueError("--capture-hz must be a positive finite number")
    if args.mode == "olat" and args.capture_hz is None:
        raise ValueError("--capture-hz is required for olat mode")
    if args.mode != "olat" and args.capture_hz is not None:
        raise ValueError("--capture-hz is only valid for olat mode")
    if args.mode == "playback" and not args.sequence_id:
        raise ValueError("--sequence-id is required for playback mode")
    if args.mode != "playback" and args.sequence_id is not None:
        raise ValueError("--sequence-id is only valid for playback mode")


def run(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[..., LightStageSyncClient] = LightStageSyncClient,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    input_func: Callable[[str], str] = input,
) -> int:
    """Run one CLI command and return a shell-style exit status.

    Errors from the client deliberately propagate, allowing callers to choose
    how to present them.  :func:`main` provides the user-facing error handling.
    """
    args = build_parser().parse_args(argv)
    if args.action is None:
        args.action = "interactive"
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
        print(
            json.dumps(result, default=_json_default, indent=2, sort_keys=True),
            file=output,
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Console-script entry point."""
    try:
        return run(argv)
    except Exception as exc:
        print(f"lscli: error: {exc}", file=sys.stderr)
        return 1


__all__ = ["DEFAULT_URI", "build_parser", "main", "run"]
