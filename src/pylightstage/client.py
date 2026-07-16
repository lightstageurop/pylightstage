import asyncio
from typing import Literal, Optional, Tuple
import cbor2
import websockets

ColorMode = Literal['rgb', 'w', 'rgbw']
PolarizationMode = Literal['up', 'cp', 'pp']


class LightStageClient:
    def __init__(self, uri: str = "ws://10.37.211.100:8080/sw"):
        """Initialise the Light Stage Client."""

        self.uri = uri
        self.websocket = None

        # Local buffer for fixture updates (used when go=False).
        self._pending_updates = {}

    async def connect(self):
        """Establish WebSocket connection to light stage server."""
        self.websocket = await websockets.connect(self.uri)

    async def close(self):
        """Safely close WebSocket connection."""
        if self.websocket:
            self.websocket.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # Utilities

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
        r, g, b = _to_16b(intensity)
        pass

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
        if not self.websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        cmd = {
            "SetFixture": {
                "arc_idx": arc,
                "light_idx": light,
                "colour": self._build_color_req(color, intensity)
            }
        }
        await self.websocket.send(cbor2.dumps(cmd))

    async def turn_off_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = 'rgbw',
        go=True
    ):
        self.turn_on_light(light, arc, color, (0, 0, 0), go)

    async def turn_on_arc(
        self,
        arc: int,
        color: ColorMode = 'rgbw',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0)
    ):
        if not self.websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        cmd = {
            "SetArc": {
                "arc_idx": arc,
                "colour": self._build_color_req(color, intensity)
            }
        }
        await self.websocket.send(cbor2.dumps(cmd))

    async def turn_off_arc(
        self,
        arc: int,
        color: ColorMode = 'rgbw',
    ):
        self.turn_on_arc(arc, color, (0, 0, 0))

    async def turn_on_lightstage(
        self,
        color: ColorMode = 'rgbw',
        intensity: Tuple[float, float, float] = (255.0, 255.0, 255.0)
    ):
        if not self.websocket:
            raise RuntimeError("Not connected to WebSocket server.")

        cmd = {
            "SetLightstage": self._build_color_req(color, intensity)
        }
        await self.websocket.send(cbor2.dumps(cmd))

    async def turn_off_lightstage(
        self,
        color: ColorMode = 'rgbw',
    ):
        self.turn_on_lightstage(arc, color, (0, 0, 0))

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
        self.turn_on_pol_light(light, arc, pol, (0, 0, 0), go)

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
        self.turn_on_horizontal_arc(light, arc, color, (0, 0, 0))
