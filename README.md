# pylightstage

`pylightstage` is a Python client for the [LightStage server WebSocket API][lsserver]. It includes an asynchronous client, a blocking wrapper, playback-sequence helpers, and `lsCLI` for one-shot command-line actions.

## Safety and scope

This package controls real lights and can trigger connected cameras. Fixture and mode commands change the connected server immediately. Confirm the endpoint, fixture indices, and intended action before using shared or production hardware. The historical default endpoint is `ws://10.37.211.100:8080/ws`; replace it with your installation's endpoint.

## Install

Install the package and its runtime dependencies:

```bash
python -m pip install pylightstage
```

To develop from a checkout:

```bash
git clone <repository-url>
cd pylightstage
python -m pip install -e ".[dev]"
```

`cbor2`, `websockets`, and `zstandard` are installed automatically.

## Core concepts

### Endpoint and connections

Clients use an `lsserver` WebSocket URI, for example:

```python
URI = "ws://lightstage.example:8080/ws"
```

Use `LightStageClient` as an async context manager or `LightStageSyncClient` as a normal context manager. Both close the WebSocket when the context exits, including after an error.

### Fixture layout, colours, and intensities

The current client models 12 arcs (`0`–`11`), each with 14 lights (`0`–`13`). Python fixture methods take the light index first and the arc index second: `set_light(light, arc, ...)`.

| `color` value | Channels updated |
| --- | --- |
| `rgb` | RGB fixture only |
| `w` | White fixture only |
| `rgbw` | RGB and white fixtures |

Intensities are three-value tuples. Every value must be finite and in the inclusive `0`–`255` range; the client converts them to the server's 16-bit fixture values. For RGB they are `(red, green, blue)`; for white they are the server's three white-channel values.

## Python API

### Async client

```python
import asyncio

from pylightstage import LightStageClient


async def main() -> None:
    async with LightStageClient("ws://lightstage.example:8080/ws") as client:
        await client.set_lightstage(color="rgb", intensity=(255, 0, 0))
        await client.trigger()
        await client.clear_lightstage()


asyncio.run(main())
```

### Blocking client

`LightStageSyncClient` runs the async implementation in a background thread and exposes the same operations as normal blocking methods:

```python
from pylightstage import LightStageSyncClient

with LightStageSyncClient("ws://lightstage.example:8080/ws") as client:
    client.set_arc(arc=2, color="w", intensity=(180, 120, 60))
    client.clear_arc(arc=2)
```

Do not call the blocking wrapper from an asynchronous event-loop callback; use `LightStageClient` there.

### Manual fixture operations

Methods on `LightStageClient` must be awaited; the synchronous wrapper uses the same names without `await`.

| Target or action | Method |
| --- | --- |
| One fixture | `set_light(light, arc, color="rgbw", intensity=(255, 255, 255))` |
| One arc | `set_arc(arc, color="rgbw", intensity=(255, 255, 255))` |
| Complete stage | `set_lightstage(color="rgbw", intensity=(255, 255, 255))` |
| One light index on every arc | `set_horizontal_arc(light, color="rgbw", intensity=(255, 255, 255))` |
| Polarized logical fixture | `set_pol_light(light, arc, pol="up", intensity=(255, 255, 255))` |
| Turn a target off | `clear_light`, `clear_arc`, `clear_lightstage`, `clear_horizontal_arc`, or `clear_pol_light` |
| Trigger capture in manual mode | `trigger()` |

`pol` accepts `up`, `cp`, and `pp`; the client maps the logical polarized fixture to the necessary RGB or white channel. `turn_on_*` and `turn_off_*` are aliases of the corresponding `set_*` and `clear_*` methods.

To send several per-fixture changes in one request, pass `go=False` to `set_light` or `clear_light`, then call `go()`:

```python
async with LightStageClient(URI) as client:
    await client.set_light(0, 0, color="rgb", intensity=(255, 0, 0), go=False)
    await client.set_light(1, 0, color="rgb", intensity=(0, 255, 0), go=False)
    await client.go()
```

`show_env_map`, `show_pol_env_map`, and `show_pol_env_map_new` accept an array-like object with shape `(168, 3)`, ordered by arc then light. They batch the map into one update. NumPy is optional; the object only needs that `shape` and iterable rows.

### Modes, configuration, and events

`get_config()` returns the server configuration dictionary and `get_mode()` returns a `StageMode` (or `None`). Use `set_mode()` or convenience methods to change mode:

```python
from pylightstage import CaptureConfig, StageMode

await client.set_mode(StageMode.DEMO)
await client.set_mode_manual()
await client.set_mode_olat(capture_hz=30.0)
await client.set_mode(StageMode.PLAYBACK, CaptureConfig(capture_hz=30.0))
```

OLAT and Playback require `CaptureConfig`; Demo and Manual do not. Register an event callback with `client.on_event(callback)`, or await one event with `await client.wait_for_event("EventName", timeout=30)`.

### Playback sequences

`SequenceBuilder` creates `PlaybackSequence` objects. Save them as CBOR (`.cbor`) or Zstandard-compressed CBOR (`.cbor.zst`); the filename suffix chooses the format.

```python
from pathlib import Path
from pylightstage import SequenceBuilder

sequence = (
    SequenceBuilder(name="red-frame", capture_hz=30.0)
    .set_lightstage(color="rgb", intensity=(255, 0, 0))
    .append_frame()
    .build()
)
sequence.save(Path("red-frame.cbor.zst"))
```

Load a saved file with `PlaybackSequence.load(path)`. Connected clients provide `upload_sequence(sequence)`, `list_sequences()`, `get_sequence(id)`, and `delete_sequence(id)`. Upload and lookup return `SequenceSummary` values with the server ID, name, capture rate, frame count, and duration.

See [`examples/`](examples/) for async, sync, event, and sequence workflows.

## Command-line interface (`lsCLI`)

The normal `lsCLI` commands are atomic: each invocation connects, performs one operation, then closes. With no action, `lscli` launches the visual interactive console; it keeps one connection open until you quit or choose a new endpoint. Use `lscli` (recommended), `lsCLI`, or the module entry point:

```bash
lscli --help
python -m pylightstage.lsCLI --help

# Guided menus for fixtures, modes, sequences, and server inspection.
lscli
lscli --uri ws://lightstage.example:8080/ws interactive
# Use plain text when recording output or using an unsupported terminal.
lscli --uri ws://lightstage.example:8080/ws interactive --no-color
```

Place global `--uri` before the command. It defaults to `ws://10.37.211.100:8080/ws`. Connection attempts time out after five seconds by default; use `--connect-timeout SECONDS` to choose another positive timeout:

```bash
lscli --uri ws://127.0.0.1:8080/ws --connect-timeout 2 interactive
```
The interactive console uses colour and clears the previous page when standard
output is a terminal. Enter `b` at a prompt to cancel or return to the preceding
menu, and `q` from the main menu to close the connection and exit.

```bash
# Inspect state. Returned data is JSON on standard output.
lscli --uri ws://lightstage.example:8080/ws get-config
lscli --uri ws://lightstage.example:8080/ws get-mode

# Set and clear a fixture.
lscli --uri ws://lightstage.example:8080/ws set-light \
  --arc 0 --light 4 --color rgb --intensity 255 0 0
lscli --uri ws://lightstage.example:8080/ws clear-light --arc 0 --light 4

# Set larger targets and a polarized fixture.
lscli --uri ws://lightstage.example:8080/ws set-arc \
  --arc 2 --color w --intensity 180 120 60
lscli --uri ws://lightstage.example:8080/ws set-lightstage \
  --color rgbw --intensity 32 32 32
lscli --uri ws://lightstage.example:8080/ws set-horizontal-arc --light 3
lscli --uri ws://lightstage.example:8080/ws set-polarized-light \
  --arc 1 --light 3 --polarization cp --color rgb --intensity 255 255 255

# Modes and manual capture.
lscli --uri ws://lightstage.example:8080/ws set-mode manual
lscli --uri ws://lightstage.example:8080/ws set-mode olat --capture-hz 30
lscli --uri ws://lightstage.example:8080/ws trigger

# Server-side sequence management.
lscli --uri ws://lightstage.example:8080/ws upload-sequence red-frame.cbor.zst
lscli --uri ws://lightstage.example:8080/ws list-sequences
lscli --uri ws://lightstage.example:8080/ws get-sequence <sequence-id>
lscli --uri ws://lightstage.example:8080/ws delete-sequence <sequence-id>
```

| Command | Purpose |
| --- | --- |
| `get-config`, `get-mode` | Print server data as JSON. |
| `interactive` (`i`) | Open a guided, reconnectable terminal console. |
| `set-mode demo\|manual\|olat\|playback` | Change mode. OLAT and Playback require `--capture-hz`. |
| `trigger` | Trigger a camera capture in manual mode. |
| `set-light` / `clear-light` | Set or clear one `--arc` / `--light` target. |
| `set-arc` / `clear-arc` | Set or clear all fixtures in `--arc`. |
| `set-lightstage` / `clear-lightstage` | Set or clear the complete stage. |
| `set-horizontal-arc` / `clear-horizontal-arc` | Set or clear `--light` across all arcs. |
| `set-polarized-light` / `clear-polarized-light` | Set or clear a polarized `--arc` / `--light` target. |
| `list-sequences`, `get-sequence`, `delete-sequence` | List, inspect, or delete server sequences. |
| `upload-sequence PATH` | Load and upload a `.cbor` or `.cbor.zst` file. |

Set commands default to `--color rgbw --intensity 255 255 255`; clear commands default to `--color rgbw`. Polarized commands accept `--polarization up`, `cp`, or `pp`. Use `lscli <command> --help` for exact command options.

The CLI writes errors to standard error and exits non-zero for invalid arguments, unreadable sequence files, connection failures, or server errors. Commands with no returned data are silent on success.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Connection refused, timeout, or no route to host | Verify the server is running, network/VPN access, and a URI of the form `ws://host:port/ws`. |
| `Not connected to WebSocket server` | Enter the client context before calling a method; do not reuse it after the context exits. |
| Arc or light validation error | Use zero-based arcs `0`–`11` and lights `0`–`13`. |
| Intensity validation error | Supply exactly three finite values from `0` through `255`. |
| `--capture-hz is required` | Supply it for CLI OLAT/Playback mode, or pass `CaptureConfig` in Python. |
| Cannot load a sequence | Check the local path and valid `.cbor` / `.cbor.zst` `PlaybackSequence` content. |

## Developing and maintaining

### Project layout

| Path | Purpose |
| --- | --- |
| `src/pylightstage/client.py` | Async client, blocking wrapper, validation, batching, modes, and events. |
| `src/pylightstage/models.py` | Public data models and sequence serialization. |
| `src/pylightstage/sequences.py` | In-memory `SequenceBuilder`. |
| `src/pylightstage/lsCLI/` | CLI parser, dispatch, JSON output, and module entry point. |
| `tests/` | Unit tests and opt-in hardware integration tests. |
| `examples/` | Runnable examples. |
| `pyproject.toml` | Package metadata, dependencies, console scripts, and pytest settings. |

### Test, package, and release changes

Run the default unit suite after installing development dependencies:

```bash
python -m pip install -e ".[dev]"
pytest
```

The default configuration excludes `integration` tests and therefore does not require a server. To run hardware tests, start a compatible test server at the URI configured in `tests/test_integration.py`, then run:

```bash
pytest -m integration
```

Integration tests can alter fixture state and server mode; run them only on a safe test installation. They attempt to restore the original mode where applicable.

### Simulate a server locally

For CLI development, run a minimal local WebSocket server in one terminal and connect the CLI from another. This simulator records the CBOR request envelope and responds `Ok` to every command; it does not control hardware.

```bash
python - <<'PY'
import asyncio
import cbor2
import websockets


async def simulated_lsserver(websocket):
    async for payload in websocket:
        request = cbor2.loads(payload)
        print("received:", request["command"])
        await websocket.send(cbor2.dumps({
            "Response": {"id": request["id"], "response": "Ok"},
        }))


async def main():
    async with websockets.serve(simulated_lsserver, "127.0.0.1", 8765):
        print("simulated lsserver listening at ws://127.0.0.1:8765/ws")
        await asyncio.Future()  # run until Ctrl-C


asyncio.run(main())
PY
```

Then, in a second terminal, run:

```bash
lscli --uri ws://127.0.0.1:8765/ws --connect-timeout 2 interactive
```

The local integration-style test in `tests/test_lscli.py` uses this same protocol. It skips only when an environment blocks local socket binding.

Before releasing, build and smoke-test the distribution in a clean environment:

```bash
python -m pip install build
python -m build
# Install the generated distribution into a clean virtual environment, then:
lscli --help
python -m pylightstage.lsCLI --help
```

Update the version and console-script declarations in `pyproject.toml` as part of a release.

### Maintaining `lsCLI`

Non-interactive CLI commands deliberately map one invocation to one `LightStageSyncClient` operation. `interactive` is the exception: it holds a client for the lifetime of the menu session and reconnects only when the user changes endpoint. When adding a command:

1. Define parser arguments and help text in `build_parser()` in `src/pylightstage/lsCLI/__init__.py`.
2. Validate command-specific argument combinations in `_validate_args()` before opening a connection.
3. Map non-interactive commands to one client call in `_dispatch()`; do not add a stateful multi-step workflow. Add guided menu flows to `lsCLI/interactive.py` and keep them usable without optional dependencies.
4. Make returned values JSON-serializable through `_json_default()`, with data on standard output and diagnostics on standard error.
5. Add hardware-free tests in `tests/test_lscli.py` using a fake client.
6. Update this command reference and run `pytest`.

`lscli` and `lsCLI` are both declared in `[project.scripts]`. Keep both pointing to `pylightstage.lsCLI:main` if the entry point changes.

### Compatibility guidelines

The public exports in `pylightstage/__init__.py`, the `set_*` / `clear_*` methods, and `turn_on_*` / `turn_off_*` aliases are user-facing API. Preserve argument order—especially `set_light(light, arc, ...)`—and retain the public 8-bit intensity range. Add a regression test for every changed request payload or fixed client bug.

## License

Distributed under the [MIT License](LICENSE).

[lsserver]: https://github.com/lightstageurop/lightstage-server-rs/tree/master/lsserver
