from typing import Tuple


def to_16b(
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
