"""Dependency-free interactive terminal interface for :mod:`pylightstage.lsCLI`."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any, Callable, TextIO


Dispatch = Callable[[Any, argparse.Namespace], Any]
JsonDefault = Callable[[Any], Any]
Input = Callable[[str], str]

_ACTION_TITLES = {
    "get-config": "Show server configuration",
    "get-mode": "Show current mode",
    "trigger": "Trigger camera capture",
    "set-mode": "Change stage mode",
    "list-sequences": "List playback sequences",
    "get-sequence": "Show playback sequence",
    "upload-sequence": "Upload playback sequence",
    "delete-sequence": "Delete playback sequence",
}
_QUERY_ACTIONS = {"get-config", "get-mode", "list-sequences", "get-sequence"}


class Terminal:
    """Small terminal renderer with an automatic plain-text fallback."""

    _RESET = "\033[0m"
    _BOLD = "\033[1m"
    _CYAN = "\033[36m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RED = "\033[31m"

    def __init__(self, output: TextIO, error: TextIO, *, color: bool | None = None):
        self.output = output
        self.error = error
        self.color = (
            getattr(output, "isatty", lambda: False)() if color is None else color
        )

    def _style(self, text: str, code: str) -> str:
        return f"{code}{text}{self._RESET}" if self.color else text

    def write(self, text: str = "") -> None:
        print(text, file=self.output)

    def clear(self) -> None:
        """Clear an interactive terminal without polluting redirected output."""
        if getattr(self.output, "isatty", lambda: False)():
            self.output.write("\033[2J\033[H")
            self.output.flush()

    def panel(self, title: str, lines: list[str]) -> None:
        width = min(88, max(54, len(title) + 8, *(len(line) + 4 for line in lines)))
        heading = self._style(f" {title} ", self._BOLD + self._CYAN)
        self.write(f"╔{heading}{'═' * max(0, width - len(title) - 4)}╗")
        for line in lines:
            visible = line[:width - 4]
            self.write(f"║ {visible:<{width - 3}}║")
        self.write(f"╚{'═' * (width - 2)}╝")

    def menu(self, title: str, options: list[tuple[str, str]]) -> None:
        self.write()
        self.write(self._style(f"── {title} ──", self._BOLD + self._CYAN))
        for key, label in options:
            self.write(f"  {self._style(f'[{key}]', self._BOLD)} {label}")

    def success(self, text: str) -> None:
        self.write(self._style(f"✓ {text}", self._GREEN))

    def warning(self, text: str) -> None:
        self.write(self._style(f"! {text}", self._YELLOW))

    def failure(self, text: str) -> None:
        print(self._style(f"✗ {text}", self._RED), file=self.error)


class InteractiveSession:
    """Guided menus for actions performed through one connected client."""

    def __init__(
        self,
        client: Any,
        uri: str,
        *,
        dispatch: Dispatch,
        json_default: JsonDefault,
        terminal: Terminal,
        input_func: Input,
    ):
        self.client = client
        self.uri = uri
        self.dispatch = dispatch
        self.json_default = json_default
        self.terminal = terminal
        self.input = input_func

    def _begin_page(self, *details: str) -> None:
        """Clear the terminal and redraw the persistent console header."""
        self.terminal.clear()
        self.terminal.panel(
            "LightStage Interactive Console",
            [f"Endpoint: {self.uri}", "Status: connected", *details],
        )

    def run(self) -> str | None:
        """Run the menu and return a replacement URI when reconnecting."""
        while True:
            self._begin_page("Choose an action below; q exits safely.")
            self.terminal.menu("Main menu", [
                ("1", "Fixtures and stage"),
                ("2", "Modes and camera capture"),
                ("3", "Playback sequences"),
                ("4", "Inspect server"),
                ("5", "Reconnect to another endpoint"),
                ("q", "Quit"),
            ])
            choice = self._choice("Select", {"1", "2", "3", "4", "5", "q"})
            if choice is None or choice == "q":
                self.terminal.success("Disconnected. Goodbye.")
                return None
            if choice == "1":
                self._fixtures()
            elif choice == "2":
                self._modes()
            elif choice == "3":
                self._sequences()
            elif choice == "4":
                self._inspect()
            else:
                replacement = self._text("New WebSocket URI", default=self.uri)
                if replacement is not None and replacement != self.uri:
                    self.terminal.success("Reconnecting to the new endpoint.")
                    return replacement

    def _fixtures(self) -> None:
        actions = {
            "1": ("set-light", "light", False),
            "2": ("clear-light", "light", False),
            "3": ("set-arc", "arc", False),
            "4": ("clear-arc", "arc", False),
            "5": ("set-lightstage", "lightstage", False),
            "6": ("clear-lightstage", "lightstage", False),
            "7": ("set-horizontal-arc", "horizontal_arc", False),
            "8": ("clear-horizontal-arc", "horizontal_arc", False),
            "9": ("set-polarized-light", "light", True),
            "10": ("clear-polarized-light", "light", True),
        }
        while True:
            self._begin_page()
            self.terminal.menu("Fixtures and stage", [
                ("1", "Set one fixture"), ("2", "Clear one fixture"),
                ("3", "Set an arc"), ("4", "Clear an arc"),
                ("5", "Set the full stage"), ("6", "Clear the full stage"),
                ("7", "Set one light index across every arc"),
                ("8", "Clear one light index across every arc"),
                ("9", "Set a polarized fixture"), ("10", "Clear a polarized fixture"),
                ("b", "Back"),
            ])
            choice = self._choice("Select", {*actions, "b"})
            if choice is None or choice == "b":
                return
            action, target, polarized = actions[choice]
            args = self._fixture_args(action, target, polarized)
            if args is not None:
                self._execute(args)

    def _fixture_args(
        self, action: str, target: str, polarized: bool
    ) -> argparse.Namespace | None:
        values: dict[str, Any] = {"action": action, "target": target}
        if target in ("light", "arc"):
            arc = self._integer("Arc [0-11]", minimum=0, maximum=11)
            if arc is None:
                return None
            values["arc"] = arc
        if target in ("light", "horizontal_arc"):
            light = self._integer("Light [0-13]", minimum=0, maximum=13)
            if light is None:
                return None
            values["light"] = light
        if polarized:
            pol = self._choice("Polarization [up/cp/pp]", {"up", "cp", "pp"}, default="up")
            if pol is None:
                return None
            values["polarization"] = pol
        else:
            colour = self._choice(
                "Colour [rgb/w/rgbw]", {"rgb", "w", "rgbw"}, default="rgbw"
            )
            if colour is None:
                return None
            values["color"] = colour
        if action.startswith("set-"):
            intensity = self._intensity()
            if intensity is None:
                return None
            values["intensity"] = intensity
        return argparse.Namespace(**values)

    def _modes(self) -> None:
        actions = {
            "1": ("get-mode", None),
            "2": ("set-mode", "demo"),
            "3": ("set-mode", "manual"),
            "4": ("set-mode", "olat"),
            "5": ("set-mode", "playback"),
            "6": ("trigger", None),
        }
        while True:
            self._begin_page()
            self.terminal.menu("Modes and camera capture", [
                ("1", "Show current mode"), ("2", "Set Demo mode"),
                ("3", "Set Manual mode"), ("4", "Set OLAT mode"),
                ("5", "Set Playback mode"), ("6", "Trigger camera capture"),
                ("b", "Back"),
            ])
            choice = self._choice("Select", {*actions, "b"})
            if choice is None or choice == "b":
                return
            action, mode = actions[choice]
            values: dict[str, Any] = {
                "action": action,
                "capture_hz": None,
                "sequence_id": None,
            }
            if mode is not None:
                values["mode"] = mode
                if mode == "olat":
                    capture_hz = self._number("Capture rate (Hz)", minimum=0.000001)
                    if capture_hz is None:
                        continue
                    values["capture_hz"] = capture_hz
                elif mode == "playback":
                    sequence_id = self._text("Uploaded sequence ID")
                    if sequence_id is None:
                        continue
                    values["sequence_id"] = sequence_id
            self._execute(argparse.Namespace(**values))

    def _sequences(self) -> None:
        while True:
            self._begin_page()
            self.terminal.menu("Playback sequences", [
                ("1", "List sequences"), ("2", "Show sequence metadata"),
                ("3", "Upload a local .cbor or .cbor.zst file"),
                ("4", "Delete a sequence"), ("b", "Back"),
            ])
            choice = self._choice("Select", {"1", "2", "3", "4", "b"})
            if choice is None or choice == "b":
                return
            if choice == "1":
                self._execute(argparse.Namespace(action="list-sequences"))
            elif choice == "2":
                sequence_id = self._text("Sequence ID")
                if sequence_id is not None:
                    self._execute(argparse.Namespace(action="get-sequence", sequence_id=sequence_id))
            elif choice == "3":
                path = self._text("Path to sequence file")
                if path is not None:
                    self._execute(argparse.Namespace(action="upload-sequence", path=Path(path)))
            else:
                sequence_id = self._text("Sequence ID")
                if sequence_id is None:
                    continue
                confirmation = self._text("Type DELETE to confirm")
                if confirmation == "DELETE":
                    self._execute(argparse.Namespace(action="delete-sequence", sequence_id=sequence_id))
                else:
                    self.terminal.warning("Delete cancelled.")
                    self._pause()

    def _inspect(self) -> None:
        while True:
            self._begin_page()
            self.terminal.menu("Inspect server", [
                ("1", "Show configuration"), ("2", "Show current mode"),
                ("3", "List sequences"), ("b", "Back"),
            ])
            choice = self._choice("Select", {"1", "2", "3", "b"})
            if choice is None or choice == "b":
                return
            action = {"1": "get-config", "2": "get-mode", "3": "list-sequences"}[choice]
            self._execute(argparse.Namespace(action=action))

    def _execute(self, args: argparse.Namespace) -> None:
        title = _ACTION_TITLES.get(
            args.action, args.action.replace("-", " ").capitalize()
        )
        self._begin_page(f"Running: {title}…")
        self.terminal.write("Waiting for the server to respond…")
        try:
            result = self.dispatch(self.client, args)
        except Exception as exc:
            self._begin_page(f"Failed: {title}")
            self.terminal.failure(str(exc))
        else:
            self._begin_page(f"Result: {title}")
            if result is None and args.action in _QUERY_ACTIONS:
                self.terminal.warning("The server returned no data.")
            else:
                self.terminal.success("Action completed.")
            if result is not None:
                self.terminal.write(json.dumps(result, default=self.json_default, indent=2, sort_keys=True))
        self._pause()

    def _text(self, label: str, *, default: str | None = None) -> str | None:
        suffix = f" [{default}]" if default is not None else ""
        while True:
            try:
                value = self.input(f"{label}{suffix} (or 'b' to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                self.terminal.write()
                return None
            if value == "b":
                return None
            if value:
                return value
            if default is not None:
                return default
            self.terminal.warning("A value is required.")

    def _choice(
        self, label: str, choices: set[str], *, default: str | None = None
    ) -> str | None:
        while True:
            value = self._text(label, default=default)
            if value is None:
                return None
            value = value.lower()
            if value in choices:
                return value
            self.terminal.warning(f"Choose one of: {', '.join(sorted(choices))}.")

    def _integer(self, label: str, *, minimum: int, maximum: int) -> int | None:
        while True:
            value = self._text(label)
            if value is None:
                return None
            try:
                number = int(value)
            except ValueError:
                self.terminal.warning("Enter a whole number.")
                continue
            if minimum <= number <= maximum:
                return number
            self.terminal.warning(f"Enter a value from {minimum} to {maximum}.")

    def _number(self, label: str, *, minimum: float) -> float | None:
        while True:
            value = self._text(label)
            if value is None:
                return None
            try:
                number = float(value)
            except ValueError:
                self.terminal.warning("Enter a number.")
                continue
            if math.isfinite(number) and number >= minimum:
                return number
            self.terminal.warning(f"Enter a value of at least {minimum:g}.")

    def _intensity(self) -> tuple[float, float, float] | None:
        while True:
            value = self._text("Intensity [R G B]", default="255 255 255")
            if value is None:
                return None
            try:
                components = tuple(float(component) for component in value.replace(",", " ").split())
            except ValueError:
                components = ()
            if len(components) == 3 and all(
                math.isfinite(component) and 0.0 <= component <= 255.0
                for component in components
            ):
                return (components[0], components[1], components[2])
            self.terminal.warning("Enter three values from 0 to 255, for example: 255 0 0.")

    def _pause(self) -> None:
        try:
            self.input("Press Enter to continue... ")
        except (EOFError, KeyboardInterrupt):
            self.terminal.write()


def run_interactive(
    uri: str,
    *,
    client_factory: Callable[..., Any],
    connect_timeout: float,
    dispatch: Dispatch,
    json_default: JsonDefault,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    input_func: Input = input,
    color: bool | None = None,
) -> int:
    """Run a reconnectable interactive session and return a shell-style status."""
    output = stdout if stdout is not None else sys.stdout
    error = stderr if stderr is not None else sys.stderr
    terminal = Terminal(output, error, color=color)
    current_uri = uri

    while True:
        try:
            with client_factory(
                uri=current_uri, connect_timeout=connect_timeout
            ) as client:
                replacement = InteractiveSession(
                    client, current_uri, dispatch=dispatch, json_default=json_default,
                    terminal=terminal, input_func=input_func,
                ).run()
        except Exception as exc:
            terminal.clear()
            terminal.panel(
                "LightStage Interactive Console",
                [f"Endpoint: {current_uri}", "Status: connection failed"],
            )
            terminal.failure(f"Could not connect to {current_uri}: {exc}")
            return 1
        if replacement is None:
            return 0
        current_uri = replacement


__all__ = ["InteractiveSession", "Terminal", "run_interactive"]
