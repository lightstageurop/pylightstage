import asyncio
import functools
import inspect
import logging
import math
import threading
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

import cbor2
import websockets

from .models import (
    CaptureConfig,
    ColorMode,
    FixtureIntensity,
    PlaybackSequence,
    PolarizationMode,
    SequenceSummary,
    StageMode,
)
from .utils import (
    color_mode,
    polarization_mode,
    polarized_color,
    to_16b,
    unit_scale,
    validate_index,
    validate_intensity,
)

logger = logging.getLogger(__name__)


class LightStageClient:
    def __init__(
        self,
        uri: str = "ws://172.30.40.238:8080/ws",
        connect_timeout: float = 5.0,
    ):
        """Initialise the Light Stage Client."""
        if not math.isfinite(connect_timeout) or connect_timeout <= 0.0:
            raise ValueError("connect_timeout must be a positive finite number")
        self._uri = uri
        self._connect_timeout = connect_timeout
        self._websocket = None
        self._req_id = 0

        self.num_arcs = 12
        self.lights_per_arc = 14

        self._event_callbacks: list[Callable[[Any], Any]] = []
        self._pending_requests: dict[int, asyncio.Future[Any]] = {}
        self._receiver_task: asyncio.Task[Any] | None = None

        # used for `wait_until_disconnected`
        self._disconnected_event = asyncio.Event()

        # Local buffer for fixture updates (used when go=False).
        # (arc_idx, light_idx) -> UpdateColourRequest
        self._pending_updates: dict[tuple[int, int], dict[str, Any]] = {}
        self._go_lock = asyncio.Lock()

    async def connect(self):
        """Establish WebSocket connection to light stage server."""
        if self._websocket is not None:
            return  # already connected

        try:
            self._websocket = await asyncio.wait_for(
                websockets.connect(self._uri), timeout=self._connect_timeout
            )
        except TimeoutError as exc:
            raise TimeoutError(
                f"Timed out connecting to {self._uri} after "
                f"{self._connect_timeout:g} seconds"
            ) from exc
        self._disconnected_event.clear()
        self._receiver_task = asyncio.create_task(self._receiver())

    async def close(self):
        """Safely close WebSocket connection."""
        websocket = self._websocket
        receiver_task = self._receiver_task
        try:
            if receiver_task:
                receiver_task.cancel()
                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass
        finally:
            try:
                if websocket:
                    await websocket.close()
            finally:
                self._receiver_task = None
                if self._websocket is websocket:
                    self._websocket = None
                self._disconnected_event.set()
                self._fail_pending_requests(RuntimeError("Connection closed by client"))

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
            logger.warning("WebSocket connection closed unexpectedly: %s", exc)
            self._fail_pending_requests(
                RuntimeError(f"WebSocket connection lost: {exc}")
            )
        except Exception as exc:
            logger.exception("Unexpected error in receiver loop")
            # fail waiting futures
            self._fail_pending_requests(exc)
        finally:
            self._websocket = None
            self._disconnected_event.set()

    def _dispatch_callback(self, callback: Callable[[Any], Any], event: Any):
        try:
            if inspect.iscoroutinefunction(callback):
                asyncio.create_task(callback(event))
            else:
                callback(event)
        except Exception:
            # if user code crashes, we don't care
            logger.exception("Error in event callback")

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
        websocket = self._websocket
        if not websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        req_id = self._next_id()
        fut = asyncio.get_running_loop().create_future()
        self._pending_requests[req_id] = fut

        try:
            payload = {
                "id": req_id,
                "command": cmd,
            }
            await websocket.send(cbor2.dumps(payload))
            resp = await asyncio.wait_for(fut, timeout=timeout)
            return self._unwrap_response(resp)
        except TimeoutError:
            raise TimeoutError(
                f"Server did not respond to command (id={req_id}, cmd={cmd}) within {timeout}s"
            )
        finally:
            self._pending_requests.pop(req_id, None)
            if not fut.done():
                fut.cancel()
            elif not fut.cancelled():
                # A receiver failure may race with a send failure. Retrieve any
                # stored exception so the abandoned future cannot emit an
                # "exception was never retrieved" warning.
                fut.exception()

    @staticmethod
    def _unwrap_response(resp: Any) -> Any:
        # WsResponse::Error
        if isinstance(resp, dict) and "Error" in resp:
            err = resp["Error"]
            raise RuntimeError(
                f"Server Error ({err.get('code')}): {err.get('message')}"
            )

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
                    SequenceSummary(**s) if isinstance(s, dict) else s for s in seq_list
                ]
        return resp

    def _validate_arc(self, arc: int) -> int:
        return validate_index("arc", arc, size=self.num_arcs)

    def _validate_light(self, light: int) -> int:
        return validate_index("light", light, size=self.lights_per_arc)

    def _build_color_req(
        self, color: ColorMode, intensity: FixtureIntensity
    ) -> dict[str, Any]:
        """Helper to build the UpdateColourRequest payload."""
        color = color_mode(color)
        intensity = validate_intensity(intensity)
        value = to_16b(intensity)
        return {
            **({"rgb": value} if color in ("rgb", "rgbw") else {}),
            **({"white": value} if color in ("w", "rgbw") else {}),
        }

    def _queue_update(self, arc: int, light: int, colour_req: dict[str, Any]):
        """Queue a colour request while allowing rgb and w requests to co-exist."""
        key = (arc, light)
        current = self._pending_updates.setdefault(key, {})
        current.update(colour_req)

    def _iter_env_map_values(self, env_map: Any, scale: float):
        if getattr(env_map, "shape", None) != (self.num_arcs * self.lights_per_arc, 3):
            raise ValueError(
                f"env_map shape is not ({self.num_arcs * self.lights_per_arc}, 3)"
            )

        scale_value = unit_scale(scale)
        for value in env_map:
            intensity = validate_intensity(value)
            yield tuple(channel * scale_value for channel in intensity)

    async def go(self):
        """Flush all buffered fixture updates to the server as a batch."""
        async with self._go_lock:
            if not self._pending_updates:
                return

            # Move the current batch out of the shared buffer before awaiting
            # the server. Updates queued while this request is in flight must
            # remain in the new buffer for the next call to go().
            updates = self._pending_updates
            self._pending_updates = {}
            fixtures = [
                {"arc_idx": arc, "light_idx": light, "colour": colour_req}
                for (arc, light), colour_req in updates.items()
            ]
            try:
                await self._send_and_recv({"SetFixtures": fixtures})
            except BaseException:
                # Retain the failed batch for retry, but let newer values win
                # when both batches update the same channel of one fixture.
                for key, colour_req in updates.items():
                    newer_req = self._pending_updates.get(key)
                    if newer_req is None:
                        self._pending_updates[key] = colour_req
                    else:
                        self._pending_updates[key] = {**colour_req, **newer_req}
                raise

    # Playback API

    async def list_sequences(self) -> list[SequenceSummary]:
        """Fetch a list of all sequence summaries from the server."""
        return await self._send_and_recv("ListSequences")

    async def get_sequence(self, sequence_id: str) -> SequenceSummary:
        """Get summary details for a specific sequence by ULID string."""
        return await self._send_and_recv({"GetSequence": str(sequence_id)})

    async def delete_sequence(self, sequence_id: str) -> None:
        """Delete a sequence on the server by ULID string."""
        await self._send_and_recv({"DeleteSequence": str(sequence_id)})

    async def upload_sequence(
        self, sequence: PlaybackSequence | dict[str, Any], timeout: float = 60.0
    ) -> SequenceSummary:
        """
        Upload a PlaybackSequence to the server.

        Uses a higher default timeout (60s) to accommodate larger frame payloads.
        """
        payload = (
            asdict(sequence) if isinstance(sequence, PlaybackSequence) else sequence
        )
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
        timeout: float | None = 30.0,
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

    async def get_config(self) -> dict[str, Any] | None:
        """Get the server's configuration."""
        return await self._send_and_recv("GetConfig")

    async def get_mode(self) -> StageMode | None:
        """Get the current operation mode of the light stage."""
        mode_str = await self._send_and_recv("GetMode")
        return StageMode(mode_str) if mode_str else None

    async def set_mode(
        self,
        mode: StageMode | str | dict[str, Any],
        config: CaptureConfig | dict[str, Any] | None = None,
        sequence_id: str | None = None,
    ):
        """
        Set the operation mode of the light stage.

        If mode is provided as a dict, it is considered a complete, opaque, payload and sent as-is.
        For known modes, the appropriate arguments should be provided.

        Args:
            mode: Target mode (StageMode, string, or full payload dict)
            config: Required for 'OLAT' mode
            sequence_id: Required for 'PLAYBACK' mode

        Raises:
            ValueError: If OLAT has no capture config or Playback has no sequence ID.
        """
        if isinstance(mode, dict):
            if config is not None or sequence_id is not None:
                raise ValueError(
                    "config and sequence_id must not be provided when mode is already the dict payload"
                )
            payload = mode

        else:
            mode_str = mode.value if isinstance(mode, StageMode) else mode
            payload: dict[str, Any] = {"type": mode_str}

            if mode_str == StageMode.OLAT.value:
                if config is None:
                    raise ValueError(
                        "CaptureConfig is required when setting mode to 'OLAT'."
                    )
                if sequence_id is not None:
                    raise ValueError(
                        "sequence_id must not be provided when setting mode to 'OLAT'."
                    )

                payload["config"] = (
                    asdict(config) if isinstance(config, CaptureConfig) else config
                )

            elif mode_str == StageMode.PLAYBACK.value:
                if sequence_id is None:
                    raise ValueError(
                        "sequence_id is required when setting mode to 'PLAYBACK'."
                    )
                if config is not None:
                    raise ValueError(
                        "config must not be provided when setting mode to 'PLAYBACK'."
                    )

                payload["id"] = str(sequence_id)

            elif config is not None or sequence_id is not None:
                raise ValueError(
                    "config and sequence_id should only be provided for one of 'OLAT' or 'PLAYBACK' modes."
                )

        cmd = {"SetMode": payload}
        return await self._send_and_recv(cmd)

    async def set_mode_demo(self):
        return await self.set_mode(StageMode.DEMO)

    async def set_mode_manual(self):
        return await self.set_mode(StageMode.MANUAL)

    async def set_mode_olat(self, capture_hz: float):
        return await self.set_mode(
            StageMode.OLAT, config=CaptureConfig(capture_hz=capture_hz)
        )

    async def set_mode_playback(self, sequence_id: str):
        """Start a playback sequence previously uploaded to the server."""
        return await self.set_mode(StageMode.PLAYBACK, sequence_id=sequence_id)

    # Manual mode API

    async def trigger(self):
        """Trigger a camera capture in manual mode."""
        await self._send_and_recv("ManualTrigger")

    async def set_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
        go=True,
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
                "SetFixture": {"arc_idx": arc, "light_idx": light, "colour": colour_req}
            }
            await self._send_and_recv(cmd)

    async def clear_light(
        self, light: int, arc: int, color: ColorMode = "rgbw", go=True
    ):
        """Turn off a single fixture."""
        await self.turn_on_light(light, arc, color, (0, 0, 0), go)

    turn_on_light = set_light
    turn_off_light = clear_light

    async def set_arc(
        self,
        arc: int,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ):
        """Set colour/intensity of an arc."""
        arc = self._validate_arc(arc)
        cmd = {
            "SetArc": {
                "arc_idx": arc,
                "colour": self._build_color_req(color, intensity),
            }
        }
        await self._send_and_recv(cmd)

    async def clear_arc(
        self,
        arc: int,
        color: ColorMode = "rgbw",
    ):
        """Turn off an arc."""
        await self.turn_on_arc(arc, color, (0, 0, 0))

    turn_on_arc = set_arc
    turn_off_arc = clear_arc

    async def set_lightstage(
        self,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ):
        """Set colour/intensity of entire light stage."""
        cmd = {"SetLightstage": self._build_color_req(color, intensity)}
        await self._send_and_recv(cmd)

    async def clear_lightstage(
        self,
        color: ColorMode = "rgbw",
    ):
        """Turn off entire lightstage"""
        await self.turn_on_lightstage(color, (0, 0, 0))

    turn_on_lightstage = set_lightstage
    turn_off_lightstage = clear_lightstage

    async def set_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = "up",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
        go=True,
    ):
        """Set one polarized logical fixture."""
        light = self._validate_light(light)
        arc = self._validate_arc(arc)
        color = polarized_color(light, arc, pol)
        await self.turn_on_light(light, arc, color, intensity, go)

    async def clear_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = "up",
        go=True,
    ):
        await self.set_pol_light(light, arc, pol, (0, 0, 0), go)

    turn_on_pol_light = set_pol_light
    turn_off_pol_light = clear_pol_light

    async def show_env_map(
        self, env_map: Any, color: ColorMode = "rgb", scale: float = 1.0
    ):
        """Show a (`num_arcs * lights_per_arc`)x3 environment map, ordered by arc then light."""
        color = color_mode(color)
        for i, value in enumerate(self._iter_env_map_values(env_map, scale)):
            light = i % self.lights_per_arc
            arc = i // self.lights_per_arc
            await self.turn_on_light(light, arc, color, value, go=False)
        await self.go()

    async def show_pol_env_map(
        self,
        env_map: Any,
        pol: PolarizationMode = "up",
        color: ColorMode = "rgbw",
        scale: float = 1.0,
    ):
        """Show a 168x3 polarized environment, optionally limited to RGB or white fixtures."""
        pol = polarization_mode(pol)
        color = color_mode(color)
        if pol == "up":
            await self.show_env_map(env_map, color, scale)
            return

        for i, value in enumerate(self._iter_env_map_values(env_map, scale)):
            light = i % self.lights_per_arc
            arc = i // self.lights_per_arc
            fixture_color = polarized_color(light, arc, pol)
            if color == "rgbw" or color == fixture_color:
                await self.turn_on_light(light, arc, fixture_color, value, go=False)
        await self.go()

    async def set_horizontal_arc(
        self,
        light: int,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ):
        """Set the same light index across all arcs."""
        light = self._validate_light(light)
        color = color_mode(color)
        for arc in range(self.num_arcs):
            await self.turn_on_light(light, arc, color, intensity, go=False)
        await self.go()

    async def clear_horizontal_arc(
        self,
        light: int,
        color: ColorMode = "rgbw",
    ):
        await self.turn_on_horizontal_arc(light, color, (0, 0, 0))

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

        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
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
            pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )

            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def _run(self, coro):
        """Allows running an async coroutine from the synchronous thread."""
        if self._loop is None or self._loop.is_closed():
            coro.close()
            raise RuntimeError("Synchronous client event loop is not running.")
        if threading.current_thread() is self._thread:
            coro.close()
            raise RuntimeError(
                "Cannot call a synchronous client method from its event-loop thread."
            )
        try:
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        except BaseException:
            coro.close()
            raise
        return future.result()  # block until coroutine returns

    def on_event(self, fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
        """Register a callback without blocking the client's event-loop thread.

        Synchronous callbacks run in a worker thread and may safely call this
        client. Async callbacks run on the client loop and must remain async.
        """

        @functools.wraps(fn)
        async def callback(event: Any):
            if inspect.iscoroutinefunction(fn):
                await fn(event)
                return

            result = await asyncio.to_thread(fn, event)
            if inspect.isawaitable(result):
                await result

        self._client.on_event(callback)
        return fn

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
        try:
            self._run(self._client.connect())
        except BaseException:
            # If connecting fails, `with` never calls __exit__.  Stop the
            # background event-loop thread here so failed CLI attempts exit.
            self.close()
            raise
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
