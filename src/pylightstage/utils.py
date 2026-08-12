import math
import operator
from collections.abc import Iterable

from .models import ColorMode, FixtureIntensity, FixtureValue, PolarizationMode

_VERTICAL_RGB_LIGHTS = frozenset({0, 2, 4, 6, 7, 9, 11, 13})


def as_index(name: str, value: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        return operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def validate_index(name: str, value: int, *, size: int) -> int:
    idx = as_index(name, value)
    if not 0 <= idx < size:
        raise IndexError(f"{name} index must be between 0 and {size - 1}")
    return idx


def color_mode(color: str) -> ColorMode:
    if color not in ("rgb", "w", "rgbw"):
        raise ValueError("color value is not one of 'rgb', 'w', or 'rgbw'")
    return color  # type: ignore[return-value]


def polarization_mode(pol: str) -> PolarizationMode:
    if pol not in ("up", "cp", "pp"):
        raise ValueError("pol (polarization) value is not one of 'up', 'cp', 'pp'")
    return pol  # type: ignore[return-value]


def polarized_color(light: int, arc: int, pol: PolarizationMode) -> ColorMode:
    """Select the physical channel for a polarized logical fixture."""
    pol = polarization_mode(pol)
    if pol == "up":
        return "rgbw"

    uses_vertical_rgb = (arc % 2 == 0) == (light in _VERTICAL_RGB_LIGHTS)
    if pol == "pp":
        return "rgb" if uses_vertical_rgb else "w"
    return "w" if uses_vertical_rgb else "rgb"


def unit_scale(value: float) -> float:
    value = float(value)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("scale value is not between 0.0 and 1.0")
    return value


def validate_intensity(intensity: Iterable[float]) -> tuple[float, float, float]:
    try:
        values = tuple(float(value) for value in intensity)
    except (TypeError, ValueError) as exc:
        raise ValueError("intensity must contain three numeric values") from exc

    if len(values) != 3:
        raise ValueError("intensity must contain exactly three numeric values")
    if not all(math.isfinite(v) for v in values):
        raise ValueError("intensity values must be finite")
    if not all(0.0 <= v <= 255.0 for v in values):
        raise ValueError("intensity values are not between 0 and 255")

    return values  # type: ignore[return-value]


def to_16b(
    intensity: FixtureIntensity = (255.0, 255.0, 255.0),
) -> FixtureValue:
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
        max(0, min(65535, int(intensity[2] * scale))),
    )
