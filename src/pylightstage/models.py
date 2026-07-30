from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, List, Literal, Tuple, TypeAlias

import cbor2
import zstandard as zstd

# Backwards compatible intensity as 0.0-255.0
FixtureIntensity: TypeAlias = Tuple[float, float, float]

# Actual fixture values as 0-65535, sent to server
FixtureValue = Tuple[int, int, int]

# Selectors for set_(light/arc/lightstage) methods
ColorMode = Literal['rgb', 'w', 'rgbw']
PolarizationMode = Literal['up', 'cp', 'pp']


class StageMode(Enum):
    """Light stage operation modes."""
    DEMO = "Demo"
    MANUAL = "Manual"
    OLAT = "OLAT"
    PLAYBACK = "Playback"


@dataclass
class CaptureConfig:
    """Configuration options for capture modes (OLAT, Playback)."""
    capture_hz: float = 30.0
