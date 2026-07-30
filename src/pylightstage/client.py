import asyncio
from dataclasses import asdict, dataclass
import functools
import inspect
import logging
import math
import operator
import threading
from typing import Any, Callable, Literal, Optional, Tuple, Union

import cbor2
import websockets

from .models import FixtureIntensity, PlaybackSequence, SequenceSummary, StageMode
from .utils import to_16b

logger = logging.getLogger("LightStageClient")


class LightStageClient:
    NUM_ARCS = 12
    LIGHTS_PER_ARC = 14
    _VERTICAL_RGB_LIGHTS = frozenset({0, 2, 4, 6, 7, 9, 11, 13})

    def __init__(self, uri: str = "ws://10.37.211.100:8080/ws"):
        """Initialise the Light Stage Client."""
        self._uri = uri
        self._websocket = None
        self._req_id = 0

        self._event_callbacks: list[Callable[[Any], Any]] = []
        self._pending_requests: dict[int, asyncio.Future] = {}
        self._receiver_task: Optional[asyncio.Task] = None

        # used for `wait_until_disconnected`
        self._disconnected_event = asyncio.Event()

        # Local buffer for fixture updates (used when go=False).
        # (arc_idx, light_idx) -> UpdateColourRequest
        self._pending_updates: dict[Tuple[int, int], dict] = {}

    async def connect(self):
        """Establish WebSocket connection to light stage server."""
        if self._websocket is not None:
            return  # already connected

        self._websocket = await websockets.connect(self._uri)
        self._disconnected_event.clear()
        self._receiver_task = asyncio.create_task(self._receiver())

    async def close(self):
        """Safely close WebSocket connection."""
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
            self._receiver_task = None

        if self._websocket:
            await self._websocket.close()
            self._websocket = None

        self._disconnected_event.set()
        self._fail_pending_requests(
            RuntimeError("Connection closed by client"))

    @property
    def is_connected(self) -> bool:
        """Returns True if WebSocket is connected."""
        return self._websocket is not None

    async def wait_until_disconnected(self):
        """Block until WebSocket disconnects."""
        await self._disconnected_event.wait()

    # Allows usage like
    #
    # async with LightStageClient() as client:
    #     await client.turn_on_light(...)
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # Receiver and events things

    async def _receiver(self):
        try:
            assert self._websocket is not None
            async for raw_msg in self._websocket:
                msg = cbor2.loads(raw_msg)
                if not isinstance(msg, dict):
                    continue

                if "Response" in msg:
                    resp_envelope = msg["Response"]
                    # match request id
                    resp_id = resp_envelope.get("id")
                    if resp_id is not None:
                        future = self._pending_requests.pop(resp_id, None)
                        if future and not future.done():
                            future.set_result(resp_envelope.get("response"))

                elif "Event" in msg:
                    event = msg["Event"]
                    for callback in list(self._event_callbacks):
                        self._dispatch_callback(callback, event)

        except asyncio.CancelledError:
            pass
        except websockets.ConnectionClosed as exc:
            logging.warning(f"WebSocket connection closed unexpectedly: {exc}")
            self._fail_pending_requests(RuntimeError(
                f"WebSocket connection lost: {exc}"))
        except Exception as exc:
            logger.error(f"Unexpected error in receiver loop: {exc}")
            # fail waiting futures
            self._fail_pending_requests(exc)
        finally:
            self._websocket = None
            self._disconnected_event.set()

    def _dispatch_callback(self, callback: Callable, event: Any):
        try:
            if inspect.iscoroutinefunction(callback):
                asyncio.create_task(callback(event))
            else:
                callback(event)
        except Exception as exc:
            # if user code crashes, we don't care
            logger.error(f"Error in event callback: {exc}")

    def _fail_pending_requests(self, exc: Exception):
        for fut in list(self._pending_requests.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._pending_requests.clear()

    # Utilities

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _send_and_recv(self, cmd: Any, timeout: float = 5.0) -> Any:
        """Helper to send CBOR message and listen for response."""
        if not self._websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        req_id = self._next_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        payload = {
            "id": req_id,
            "command": cmd,
        }
        await self._websocket.send(cbor2.dumps(payload))

        try:
            resp = await asyncio.wait_for(fut, timeout=timeout)
            return self._unwrap_response(resp)
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Server did not respond to command (id={req_id}, cmd={cmd}) within {timeout}s")
        finally:
            self._pending_requests.pop(req_id, None)

    @staticmethod
    def _unwrap_response(resp: Any) -> Any:
        # WsResponse::Error
        if isinstance(resp, dict) and "Error" in resp:
            err = resp["Error"]
            raise RuntimeError(
                f"Server Error ({err.get('code')}): {err.get('message')}")

        # WsResponse::Ok
        if resp == "Ok":
            return None
        if isinstance(resp, dict):
            # WsResponse::Mode
            if "Mode" in resp:
                return resp["Mode"]
            # WsResponse::Config
            if "Config" in resp:
                return resp["Config"]
            # WsResponse::Sequence
            if "Sequence" in resp:
                seq = resp["Sequence"]
                return SequenceSummary(**seq) if isinstance(seq, dict) else seq
            # WsResponse::SequenceList
            if "SequenceList" in resp:
                seq_list = resp["SequenceList"]
                return [
                    SequenceSummary(**s) if isinstance(s, dict) else s
                    for s in seq_list
                ]
        return resp

    @staticmethod
    def _to_16b(
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0),
    ) -> Tuple[int, int, int]:
        """
        Utility to scale 0.0-255.0 inputs to uint16 (0-65535).

        This exists because the old library (lightstage.py) exposed 8-bit inputs,
        and this library tries to replicate this as closely as possible,
        while the new light stage server expects 16-bit.
        """
        scale = 65535.0 / 255.0
        return (
            max(0, min(65535, int(intensity[0] * scale))),
            max(0, min(65535, int(intensity[1] * scale))),
            max(0, min(65535, int(intensity[2] * scale)))
        )

    @staticmethod
    def _as_index(name: str, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{name} must be an integer")
        try:
            return operator.index(value)
        except TypeError as exc:
            raise ValueError(f"{name} must be an integer") from exc

    @classmethod
    def _validate_arc(cls, arc: int) -> int:
        arc_idx = cls._as_index("arc", arc)
        if not 0 <= arc_idx < cls.NUM_ARCS:
            raise ValueError(
                f"arc value is not between 0 and {cls.NUM_ARCS - 1}")
        return arc_idx

    @classmethod
    def _validate_light(cls, light: int) -> int:
        light_idx = cls._as_index("light", light)
        if not 0 <= light_idx < cls.LIGHTS_PER_ARC:
            raise ValueError(
                f"light value is not between 0 and {cls.LIGHTS_PER_ARC - 1}")
        return light_idx

    @staticmethod
    def _validate_color(color: str) -> ColorMode:
        if color not in ('rgb', 'w', 'rgbw'):
            raise ValueError("color value is not one of 'rgb', 'w', or 'rgbw'")
        return color  # type: ignore[return-value]

    @staticmethod
    def _validate_pol(pol: str) -> PolarizationMode:
        if pol not in ('up', 'cp', 'pp'):
            raise ValueError(
                "pol (polarization) value is not one of 'up', 'cp', 'pp'")
        return pol  # type: ignore[return-value]

    @staticmethod
    def _validate_intensity(intensity: Any) -> Tuple[float, float, float]:
        try:
            values = tuple(float(value) for value in intensity)
        except (TypeError, ValueError) as exc:
            raise ValueError("intensity must contain three numeric values") from exc

        if len(values) != 3:
            raise ValueError("intensity must contain three numeric values")
        if not all(math.isfinite(value) for value in values):
            raise ValueError("intensity values must be finite")
        if min(values) < 0.0 or max(values) > 255.0:
            raise ValueError("intensity values are not between 0 and 255")
        return values

    @staticmethod
    def _validate_scale(scale: float) -> float:
        scale_value = float(scale)
        if not math.isfinite(scale_value) or not 0.0 <= scale_value <= 1.0:
            raise ValueError("scale value is not between 0.0 and 1.0")
        return scale_value

    def _build_color_req(self, color: ColorMode, intensity: Tuple[float, float, float]) -> dict:
        """Helper to build the UpdateColourRequest payload."""
        color = self._validate_color(color)
        intensity = self._validate_intensity(intensity)
        value = self._to_16b(intensity)
        return {
            **({"rgb": value} if color in ('rgb', 'rgbw') else {}),
            **({"white": value} if color in ('w', 'rgbw') else {}),
        }

    def _queue_update(self, arc: int, light: int, colour_req: dict):
        key = (arc, light)
        current = self._pending_updates.setdefault(key, {})
        current.update(colour_req)

    def _iter_env_map_values(self, env_map: Any, scale: float):
        if getattr(env_map, "shape", None) != (self.NUM_ARCS * self.LIGHTS_PER_ARC, 3):
            raise ValueError(
                f"env_map shape is not ({self.NUM_ARCS * self.LIGHTS_PER_ARC}, 3)")

        scale_value = self._validate_scale(scale)
        for value in env_map:
            intensity = self._validate_intensity(value)
            yield tuple(channel * scale_value for channel in intensity)

    @classmethod
    def _polarized_color(cls, light: int, arc: int, pol: PolarizationMode) -> ColorMode:
        pol = cls._validate_pol(pol)
        if pol == 'up':
            return 'rgbw'

        uses_vertical_rgb = (
            arc % 2 == 0) == (light in cls._VERTICAL_RGB_LIGHTS)
        if pol == 'pp':
            return 'rgb' if uses_vertical_rgb else 'w'
        return 'w' if uses_vertical_rgb else 'rgb'

    async def go(self):
        """Flush all buffered fixture updates to the server as a batch."""
        if not self._pending_updates:
            return

        fixtures = [
            {
                "arc_idx": arc,
                "light_idx": light,
                "colour": colour_req
            }
            for (arc, light), colour_req in self._pending_updates.items()
        ]
        await self._send_and_recv({"SetFixtures": fixtures})
        self._pending_updates.clear()

    # Playback API

    async def list_sequences(self) -> List[SequenceSummary]:
        """Fetch a list of all sequence summaries from the server."""
        return await self._send_and_recv("ListSequences")

    async def get_sequence(self, sequence_id: str) -> SequenceSummary:
        """Get summary details for a specific sequence by ULID string."""
        return await self._send_and_recv({"GetSequence": str(sequence_id)})

    async def delete_sequence(self, sequence_id: str) -> None:
        """Delete a sequence on the server by ULID string."""
        await self._send_and_recv({"DeleteSequence": str(sequence_id)})

    async def upload_sequence(
        self, sequence: Union[PlaybackSequence, dict], timeout: float = 60.0
    ) -> SequenceSummary:
        """
        Upload a PlaybackSequence to the server.

        Uses a higher default timeout (60s) to accommodate larger frame payloads.
        """
        payload = asdict(sequence) if isinstance(
            sequence, PlaybackSequence) else sequence
        return await self._send_and_recv({"UploadSequence": payload}, timeout=timeout)

    # Events

    def on_event(self, fn: Callable[[Any], None]) -> Callable[[Any], None]:
        """Register an event callback handler."""
        self._event_callbacks.append(fn)
        return fn

    async def wait_for_event(
        self,
        event_name: str,
        # predicate: Optional[Callable[[Any], bool]] = None
        timeout: Optional[float] = 30.0
    ) -> Any:
        """Block until a specific event arrives."""
        fut = asyncio.get_running_loop().create_future()

        def _check_event(event):
            name = None
            if isinstance(event, str):
                name = event
            elif isinstance(event, dict) and event:
                name = next(iter(event.keys()))
            if name == event_name and not fut.done():
                fut.set_result(event)

        self.on_event(_check_event)

        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            if _check_event in self._event_callbacks:
                self._event_callbacks.remove(_check_event)

    # Configuration and Modes

    async def get_config(self) -> Optional[dict]:
        """Get the server's configuration."""
        return await self._send_and_recv("GetConfig")

    async def get_mode(self) -> Optional[StageMode]:
        """Get the current operation mode of the light stage."""
        mode_str = await self._send_and_recv("GetMode")
        return StageMode(mode_str) if mode_str else None

    @staticmethod
    def _config_payload(config: Optional[Union[CaptureConfig, dict]]) -> Optional[dict]:
        return asdict(config) if isinstance(config, CaptureConfig) else config

    @classmethod
    def _mode_request(cls, mode: Union[StageMode, str, dict], config: Optional[Union[CaptureConfig, dict]]) -> dict:
        if isinstance(mode, dict):
            cmd = dict(mode)
            mode_type = cmd.get("type")
            if isinstance(mode_type, StageMode):
                mode_type = mode_type.value
                cmd["type"] = mode_type
            if isinstance(cmd.get("config"), CaptureConfig):
                cmd["config"] = asdict(cmd["config"])
            if config is not None:
                cmd["config"] = cls._config_payload(config)
        else:
            mode_type = mode.value if isinstance(mode, StageMode) else mode
            cmd = {"type": mode_type}
            config_payload = cls._config_payload(config)
            if config_payload is not None:
                cmd["config"] = config_payload

        if cmd.get("type") in ("OLAT", "Playback") and "config" not in cmd:
            raise ValueError(
                f"CaptureConfig is required when setting mode to '{cmd.get('type')}'.")
        return cmd

    async def set_mode(self, mode: Union[StageMode, str, dict], config: Optional[Union[CaptureConfig, dict]] = None):
        """
        Set the operation mode of the light stage.

        Args:
            mode: Target mode
            config: Required for 'OLAT' mode
            sequence_id: Required for 'PLAYBACK' mode

        Raises:
            ValueError: If no config provided for OLAT or Playback modes
        """
        cmd = {"SetMode": self._mode_request(mode, config)}
        return await self._send_and_recv(cmd)

    async def set_mode_demo(self):
        return await self.set_mode(StageMode.DEMO)

    async def set_mode_manual(self):
        return await self.set_mode(StageMode.MANUAL)

    async def set_mode_olat(self, capture_hz: float):
        return await self.set_mode(StageMode.OLAT, config=CaptureConfig(capture_hz=capture_hz))

    async def set_mode_playback(self, capture_hz: float):
        return await self.set_mode(StageMode.PLAYBACK, config=CaptureConfig(capture_hz=capture_hz))

    # Manual mode API

    async def trigger(self):
        """Trigger a camera capture in manual mode."""
        await self._send_and_recv("ManualTrigger")

    async def set_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
        go=True
    ):
        """Set colour/intensity of a single fixture."""
        light = self._validate_light(light)
        arc = self._validate_arc(arc)
        colour_req = self._build_color_req(color, intensity)

        if not go:
            self._queue_update(arc, light, colour_req)
            return

        if self._pending_updates:
            self._queue_update(arc, light, colour_req)
            await self.go()
        else:
            cmd = {
                "SetFixture": {
                    "arc_idx": arc,
                    "light_idx": light,
                    "colour": colour_req
                }
            }
            await self._send_and_recv(cmd)

    async def clear_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
        go=True
    ):
        """Turn off a single fixture."""
        await self.turn_on_light(light, arc, color, (0, 0, 0), go)

    turn_on_light = set_light
    turn_off_light = clear_light

    async def set_arc(
        self,
        arc: int,
        color: ColorMode = 'rgbw',
        intensity: FixtureIntensity = (255.0, 255.0, 255.0)
    ):
        """Set colour/intensity of an arc."""
        arc = self._validate_arc(arc)
        cmd = {
            "SetArc": {
                "arc_idx": arc,
                "colour": self._build_color_req(color, intensity)
            }
        }
        await self._send_and_recv(cmd)

    async def clear_arc(
        self,
        arc: int,
        color: ColorMode = 'rgbw',
    ):
        """Turn off an arc."""
        await self.turn_on_arc(arc, color, (0, 0, 0))

    turn_on_arc = set_arc
    turn_off_arc = clear_arc

    async def set_lightstage(
        self,
        color: ColorMode = 'rgbw',
        intensity: FixtureIntensity = (255.0, 255.0, 255.0)
    ):
        """Set colour/intensity of entire light stage."""
        cmd = {
            "SetLightstage": self._build_color_req(color, intensity)
        }
        await self._send_and_recv(cmd)

    async def clear_lightstage(
        self,
        color: ColorMode = 'rgbw',
    ):
        """Turn off entire lightstage"""
        await self.turn_on_lightstage(color, (0, 0, 0))

    turn_on_lightstage = set_lightstage
    turn_off_lightstage = clear_lightstage

    async def set_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = 'up',
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
        go=True
    ):
        """Set one polarized logical fixture."""
        light = self._validate_light(light)
        arc = self._validate_arc(arc)
        color = self._polarized_color(light, arc, pol)
        await self.turn_on_light(light, arc, color, intensity, go)

    async def clear_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = 'up',
        go=True,
    ):
        await self.turn_on_pol_light(light, arc, pol, (0, 0, 0), go)

    async def show_env_map(
        self,
        env_map: Any,
        color: ColorMode = 'rgb',
        scale: float = 1.0
    ):
        """Show a 168x3 environment map, ordered by arc then light."""
        color = self._validate_color(color)
        for i, value in enumerate(self._iter_env_map_values(env_map, scale)):
            light = i % self.LIGHTS_PER_ARC
            arc = i // self.LIGHTS_PER_ARC
            await self.turn_on_light(light, arc, color, value, go=False)
        await self.go()

    async def show_pol_env_map(
        self,
        env_map: Any,
        pol: PolarizationMode = 'up',
        scale: float = 1.0
    ):
        """Show a 168x3 environment map through the polarization layout."""
        pol = self._validate_pol(pol)
        if pol == 'up':
            await self.show_env_map(env_map, 'rgbw', scale)
            return

        for i, value in enumerate(self._iter_env_map_values(env_map, scale)):
            light = i % self.LIGHTS_PER_ARC
            arc = i // self.LIGHTS_PER_ARC
            await self.turn_on_pol_light(light, arc, pol, value, go=False)
        await self.go()

    async def show_pol_env_map_new(
        self,
        env_map: Any,
        pol: PolarizationMode = 'up',
        color: ColorMode = 'rgbw',
        scale: float = 1.0
    ):
        """Show a polarized environment map, optionally limited to RGB or white fixtures."""
        pol = self._validate_pol(pol)
        color = self._validate_color(color)
        if pol == 'up':
            await self.show_env_map(env_map, color, scale)
            return

        for i, value in enumerate(self._iter_env_map_values(env_map, scale)):
            light = i % self.LIGHTS_PER_ARC
            arc = i // self.LIGHTS_PER_ARC
            polarized_color = self._polarized_color(light, arc, pol)
            if color == 'rgbw' or color == polarized_color:
                await self.turn_on_light(light, arc, polarized_color, value, go=False)
        await self.go()

    async def turn_on_horizontal_arc(
        self,
        light: int,
        color: ColorMode = 'rgbw',
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ):
        """Set the same light index across all arcs."""
        light = self._validate_light(light)
        color = self._validate_color(color)
        for arc in range(self.NUM_ARCS):
            await self.turn_on_light(light, arc, color, intensity, go=False)
        await self.go()

    async def clear_horizontal_arc(
        self,
        light: int,
        color: ColorMode = 'rgbw',
    ):
        await self.turn_on_horizontal_arc(light, color=color, intensity=(0, 0, 0))

    turn_on_horizontal_arc = set_horizontal_arc
    turn_off_horizontal_arc = clear_horizontal_arc


class LightStageSyncClient:
    """
    Synchronous wrapper for LightStageClient.

    This class runs an asyncio event loop in a background thread,
    allowing async websocket operations to happen while exposing regular blocking methods.
    """
    _LOOP_KEEPALIVE_SECONDS = 0.05

    def __init__(self, *args, **kwargs):
        # Underlying async implementation
        self._client = LightStageClient(*args, **kwargs)

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True
        )
        self._thread.start()

        # Block until event loop is running
        self._ready.wait()

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()

        def keepalive():
            if self._loop is not None and not self._loop.is_closed():
                self._loop.call_later(self._LOOP_KEEPALIVE_SECONDS, keepalive)

        # Bounds callback latency on platforms where cross-thread selector wakeups are delayed.
        self._loop.call_soon(keepalive)

        try:
            self._loop.run_forever()
        finally:
            pending = [t for t in asyncio.all_tasks(
                self._loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True))

            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def _run(self, coro):
        """Allows running an async coroutine from the synchronous thread."""
        if self._loop is None:
            raise RuntimeError("Synchronous client event loop is not running.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()  # block until coroutine returns

    def close(self):
        if not self._thread.is_alive():
            return

        try:
            self._run(self._client.close())
        finally:
            assert self._loop is not None
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()

    # Allows usage like
    #
    # with LightStageSyncClient() as client:
    #     client.turn_on_light(...)
    def __enter__(self):
        self._run(self._client.connect())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # Forward any other attributes to the underlying async client,
    # wrapping everything so it can be called from sync code.
    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._client, name)

        if inspect.iscoroutinefunction(attr):
            @functools.wraps(attr)
            def wrapper(*args, **kwargs):
                return self._run(attr(*args, **kwargs))
            return wrapper

        return attr
