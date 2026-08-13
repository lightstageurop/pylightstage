from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, TypeAlias

import cbor2
import zstandard as zstd

# Backwards compatible intensity as 0.0-255.0
FixtureIntensity: TypeAlias = tuple[float, float, float]

# Actual fixture values as 0-65535, sent to server
FixtureValue = tuple[int, int, int]

# Selectors for set_(light/arc/lightstage) methods
ColorMode = Literal["rgb", "w", "rgbw"]
PolarizationMode = Literal["up", "cp", "pp"]


class StageMode(StrEnum):
    """Light stage operation modes."""

    DEMO = "Demo"
    MANUAL = "Manual"
    OLAT = "OLAT"
    PLAYBACK = "Playback"


@dataclass
class CaptureConfig:
    """Configuration options for capture modes (OLAT, Playback)."""

    capture_hz: float = 30.0


@dataclass(frozen=True)
class SequenceSummary:
    """Metadata about a playback sequence."""

    id: str
    name: str
    capture_hz: float
    total_frames: int
    duration_secs: float


@dataclass(frozen=True)
class StageFrame:
    """A single frame, capturing the states of all white and colour fixtures on the light stage."""

    white_fixtures: list[list[FixtureValue]] = field(default_factory=list)
    rgb_fixtures: list[list[FixtureValue]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "white_fixtures": self.white_fixtures,
            "rgb_fixtures": self.rgb_fixtures,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageFrame":
        def normalise(grid: Any) -> list[list[FixtureValue]]:
            return [[tuple(val) for val in row] for row in (grid or [])]

        return cls(
            white_fixtures=normalise(data.get("white_fixtures", [])),
            rgb_fixtures=normalise(data.get("rgb_fixtures", [])),
        )


@dataclass(frozen=True)
class PlaybackSequence:
    """
    A sequence of frames for the light stage to display.

    Can be constructed using a SequenceBuilder, and loaded from / stored to disk as either
    compressed or uncompressed CBOR data.
    """

    name: str
    capture_hz: float
    frames: list[StageFrame] = field(default_factory=list)

    @property
    def total_frames(self) -> int:
        return len(self.frames)

    @property
    def duration_secs(self) -> float:
        return self.total_frames / self.capture_hz if self.capture_hz > 0 else 0.0

    def to_summary(self, seq_id: str = "00000000000000000000000000") -> SequenceSummary:
        """Generate a summary for a local file (not using lsserver)."""
        return SequenceSummary(
            id=seq_id,
            name=self.name,
            capture_hz=self.capture_hz,
            total_frames=self.total_frames,
            duration_secs=self.duration_secs,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "capture_hz": self.capture_hz,
            "frames": [frame.to_dict() for frame in self.frames],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlaybackSequence":
        return cls(
            name=data["name"],
            capture_hz=data["capture_hz"],
            frames=[StageFrame.from_dict(f) for f in data.get("frames", [])],
        )

    def to_cbor(self) -> bytes:
        return cbor2.dumps(self.to_dict())

    @classmethod
    def from_cbor(cls, payload: bytes) -> "PlaybackSequence":
        data = cbor2.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("Invalid CBOR payload for PlaybackSequence")  # noqa: TRY004
        return cls.from_dict(data)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        payload = self.to_cbor()

        if path.suffix == ".zst" or path.name.endswith(".cbor.zst"):
            cctx = zstd.ZstdCompressor()
            path.write_bytes(cctx.compress(payload))
        else:
            path.write_bytes(payload)

    @classmethod
    def load(cls, path: str | Path) -> "PlaybackSequence":
        path = Path(path)
        payload = path.read_bytes()

        if path.suffix == ".zst" or path.name.endswith(".cbor.zst"):
            dctx = zstd.ZstdDecompressor()
            payload = dctx.decompress(payload)

        return cls.from_cbor(payload)
