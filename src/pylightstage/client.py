import asyncio
import threading
from typing import Literal, Optional, Tuple, Any
import inspect
import functools

import cbor2
import websockets

ColorMode = Literal['rgb', 'w', 'rgbw']
PolarizationMode = Literal['up', 'cp', 'pp']


class LightStageClient:
    def __init__(self, uri: str = "ws://10.37.211.100:8080/ws"):
        """Initialise the Light Stage Client."""

        self._uri = uri
        self._websocket = None

        # Local buffer for fixture updates (used when go=False).
        self._pending_updates = {}

    async def connect(self):
        """Establish WebSocket connection to light stage server."""
        self._websocket = await websockets.connect(self._uri)

    async def close(self):
        """Safely close WebSocket connection."""
        if self._websocket:
            await self._websocket.close()

    # Allows usage like
    #
    # async with LightStageClient() as client:
    #     await client.turn_on_light(...)
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # Utilities

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

    def _build_color_req(self, color: ColorMode, intensity: Tuple[float, float, float]) -> dict:
        """Helper to build the UpdateColourRequest payload."""
        value = self._to_16b(intensity)
        return {
            **({"rgb": value} if color in ('rgb', 'rgbw') else {}),
            **({"white": value} if color in ('w', 'rgbw') else {}),
        }

    async def go(self):
        """Flush all buffered fixture updates to the server as a batch."""
        pass

    # Configuration

    async def get_config(self) -> Optional[dict]:
        pass

    async def get_mode(self) -> Optional[dict]:
        pass

    async def set_mode(self, mode):
        pass

    # Manual mode API

    async def turn_on_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0),
        go=True
    ):
        """Set colour/intensity of a single fixture."""
        if not self._websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        cmd = {
            "SetFixture": {
                "arc_idx": arc,
                "light_idx": light,
                "colour": self._build_color_req(color, intensity)
            }
        }
        await self._websocket.send(cbor2.dumps(cmd))

    async def turn_off_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
        go=True
    ):
        """Turn off a single fixture."""
        await self.turn_on_light(light, arc, color, (0, 0, 0), go)

    async def turn_on_arc(
        self,
        arc: int,
        color: ColorMode = 'rgbw',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0)
    ):
        """Set colour/intensity of an arc."""
        if not self._websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        cmd = {
            "SetArc": {
                "arc_idx": arc,
                "colour": self._build_color_req(color, intensity)
            }
        }
        await self._websocket.send(cbor2.dumps(cmd))

    async def turn_off_arc(
        self,
        arc: int,
        color: ColorMode = 'rgbw',
    ):
        """Turn off an arc."""
        await self.turn_on_arc(arc, color, (0, 0, 0))

    async def turn_on_lightstage(
        self,
        color: ColorMode = 'rgbw',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0)
    ):
        """Set colour/intensity of entire light stage."""
        if not self._websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        cmd = {
            "SetLightstage": self._build_color_req(color, intensity)
        }
        await self._websocket.send(cbor2.dumps(cmd))

    async def turn_off_lightstage(
        self,
        color: ColorMode = 'rgbw',
    ):
        """Turn off entire lightstage"""
        await self.turn_on_lightstage(color, (0, 0, 0))

    async def turn_on_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = 'up',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0),
        go=True
    ):
        pass

    async def turn_off_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = 'up',
        go=True,
    ):
        await self.turn_on_pol_light(light, arc, pol, (0, 0, 0), go)

    async def turn_on_horizontal_arc(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0),
    ):
        pass

    async def turn_off_horizontal_arc(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
    ):
        await self.turn_on_horizontal_arc(light, arc, color, (0, 0, 0))


class LightStageSyncClient:
    """
    Synchronous wrapper for LightStageClient.

    This class runs an asyncio event loop in a background thread,
    allowing async websocket operations to happen while exposing regular blocking methods.
    """

    def __init__(self, *args, **kwargs):
        # Underlying async implementation
        self._client = LightStageClient(*args, **kwargs)

        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True
        )
        self._thread.start()

        # Block until event loop is running
        self._ready.wait()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)

        # Tell main thread we're ready
        self._loop.call_soon_threadsafe(self._ready.set)

        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def _run(self, coro):
        """Allows running an async coroutine from the synchronous thread."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result()  # block until coroutine returns

    def close(self):
        try:
            self._run(self._client.close())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()

    # Allows usage like
    #
    # with LightStageClient() as client:
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
