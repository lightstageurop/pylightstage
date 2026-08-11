# pylightstage

A Python library and client for the [LightStage server WebSocket API][lsserver].

This includes an asynchronous client, blocking wrapper, playback-sequence helpers, and `lscli` for one-shot command-line actions.

> [!CAUTION]
> ICL's light stage has very bright fixtures that can flash at frequencies up to around 30 Hz.
> Exposure to lights flashing between 3 and 30Hz **can trigger photosensitive epilepsy (PSE) or seizures**.
> Be careful when running custom playback sequences.

## Install

Install the package from PyPI:

```bash
python -m pip install pylightstage
```

Or from git:

```bash
git clone https://github.com/lightstageurop/pylightstage.git
python3 -m pip install .
```

For development documentation, see [CONTRIBUTING.md](CONTRIBUTING.md).

## Usage

See [examples/](examples/) for how to use the library.

Basic usage might look like this:

```py
import asyncio

URI = "ws://10.37.211.100:8080/ws"

async def main():
    async with LightStageClient(uri=URI) as client:
        await client.turn_on_lightstage(color="rgbw", intensity=(255.0, 0.0, 0.0))

if __name__ == "__main__":
    asyncio.run(main())
```

> [!NOTE]
> The historical default endpoint is `ws://10.37.211.100:8080/ws`; replace it with your installation's endpoint.

### Command-line interface (`lscli`)

The normal `lscli` commands are atomic: each invocation connects, performs one operation, then closes.

Once installed, run `lscli`, or the module entry point:

```bash
lscli --help
python -m pylightstage.lscli --help
```

For all commands you can specify a full websocket uri with `--uri`, before the command, like so:

```bash
lscli [--uri=ws://lightstage.example:8080/ws] {command}
```

Omitting `--uri` will default to `ws://10.37.211.100:8080/ws`.

With no action, `lscli` launches the visual interactive console.

```bash
lscli [--uri=...]
lscli [--uri=...] interactive
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
  --arc 1 --light 3 --polarization cp --intensity 255 255 255

# Modes and manual capture.
lscli --uri ws://lightstage.example:8080/ws set-mode manual
lscli --uri ws://lightstage.example:8080/ws set-mode olat --capture-hz 30
lscli --uri ws://lightstage.example:8080/ws trigger

# Server-side sequence management.
lscli --uri ws://lightstage.example:8080/ws upload-sequence red-frame.cbor.zst
lscli --uri ws://lightstage.example:8080/ws list-sequences
lscli --uri ws://lightstage.example:8080/ws get-sequence SEQUENCE_ID
lscli --uri ws://lightstage.example:8080/ws set-mode playback --sequence-id SEQUENCE_ID
lscli --uri ws://lightstage.example:8080/ws delete-sequence SEQUENCE_ID
```

| Command | Purpose |
| --- | --- |
| `get-config`, `get-mode` | Print server data as JSON. |
| `interactive` (`i`) | Open a guided, reconnectable terminal console. |
| `set-mode demo\|manual\|olat\|playback` | Change mode. OLAT requires `--capture-hz`; Playback requires `--sequence-id`. |
| `trigger` | Trigger a camera capture in manual mode. |
| `set-light` / `clear-light` | Set or clear one `--arc` / `--light` target. |
| `set-arc` / `clear-arc` | Set or clear all fixtures in `--arc`. |
| `set-lightstage` / `clear-lightstage` | Set or clear the complete stage. |
| `set-horizontal-arc` / `clear-horizontal-arc` | Set or clear `--light` across all arcs. |
| `set-polarized-light` / `clear-polarized-light` | Set or clear a polarized `--arc` / `--light` target. |
| `list-sequences`, `get-sequence`, `delete-sequence` | List, inspect, or delete server sequences. |
| `upload-sequence PATH` | Load and upload a `.cbor` or `.cbor.zst` file. |

Set commands default to `--color rgbw --intensity 255 255 255`; clear commands default to `--color rgbw`. Polarized commands accept `--polarization up`, `cp`, or `pp`, and select the appropriate RGB or white channel automatically. Use `lscli <command> --help` for exact command options.

The CLI exits non-zero for invalid arguments, unreadable sequence files, connection failures, or server errors. Commands with no returned data are silent on success.

## License

Distributed under the [MIT License](LICENSE).

[lsserver]: https://github.com/lightstageurop/lightstage-server-rs/tree/master/lsserver
