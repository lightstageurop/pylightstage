import copy
from typing import Self, Tuple

from .models import (
    ColorMode,
    FixtureIntensity,
    PlaybackSequence,
    PolarizationMode,
    StageFrame,
)
from .utils import color_mode, to_16b, validate_index, validate_intensity


class SequenceBuilder:
    """Mutable builder for constructing playback sequences."""

    def __init__(
        self,
        name: str,
        capture_hz: float = 30.0,
        num_arcs: int = 12,
        lights_per_arc: int = 14,
        auto_clear: bool = False,
    ):
        """
        Initialise a builder.

        The builder maintains a mutable current stage state.
        Calling `append_frame()` snapshots the current state into a frame.
        This is similar to `go()` for manual mode.
        """
        if capture_hz <= 0:
            raise ValueError("capture_hz must be > 0")
        if num_arcs <= 0:
            raise ValueError("num_arcs must be > 0")
        if lights_per_arc <= 0:
            raise ValueError("lights_per_arc must be > 0")

        self.name = name
        self.capture_hz = capture_hz
        self.num_arcs = num_arcs
        self.lights_per_arc = lights_per_arc
        self.auto_clear = auto_clear

        self.frames: list[StageFrame] = []

        self._current_white = [
            [(0, 0, 0) for _ in range(lights_per_arc)] for _ in range(num_arcs)
        ]
        self._current_rgb = [
            [(0, 0, 0) for _ in range(lights_per_arc)] for _ in range(num_arcs)
        ]

    def _validate_arc(self, arc: int) -> int:
        return validate_index("arc", arc, size=self.num_arcs)

    def _validate_light(self, light: int) -> int:
        return validate_index("light", light, size=self.lights_per_arc)

    def set_light(
        self,
        light: int,
        arc: int,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ) -> Self:
        """Set colour/intensity of a single fixture for current frame."""
        arc = self._validate_arc(arc)
        light = self._validate_light(light)
        color = color_mode(color)
        intensity = validate_intensity(intensity)

        val_16b = to_16b(intensity)
        if color in ("rgb", "rgbw"):
            self._current_rgb[arc][light] = val_16b
        if color in ("w", "rgbw"):
            self._current_white[arc][light] = val_16b

        return self

    def clear_light(self, light: int, arc: int, color: ColorMode = "rgbw") -> Self:
        """Turn off a single fixture for current frame."""
        return self.set_light(light, arc, color, (0, 0, 0))

    turn_on_light = set_light
    turn_off_light = clear_light

    def set_arc(
        self,
        arc: int,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ) -> Self:
        """Set colour/intensity of an arc for current frame."""
        for light in range(self.lights_per_arc):
            self.turn_on_light(light, arc, color, intensity)

        return self

    def clear_arc(
        self,
        arc: int,
        color: ColorMode = "rgbw",
    ) -> Self:
        """Turn off an arc for current frame."""
        return self.set_arc(arc, color, (0, 0, 0))

    turn_on_arc = set_arc
    turn_off_arc = clear_arc

    def set_lightstage(
        self,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ) -> Self:
        """Set colour/intensity of entire light stage for current frame."""
        for arc in range(self.num_arcs):
            self.turn_on_arc(arc, color, intensity)

        return self

    def clear_lightstage(
        self,
        color: ColorMode = "rgbw",
    ) -> Self:
        """Turn off entire lightstage for current frame."""
        return self.set_lightstage(color, (0, 0, 0))

    turn_on_lightstage = set_lightstage
    turn_off_lightstage = clear_lightstage

    def set_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = "up",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ) -> Self:
        raise NotImplementedError()

    def clear_pol_light(
        self,
        light: int,
        arc: int,
        pol: PolarizationMode = "up",
    ) -> Self:
        self.turn_on_pol_light(light, arc, pol, (0, 0, 0))
        return self

    turn_on_pol_light = set_pol_light
    turn_off_pol_light = clear_pol_light

    def set_horizontal_arc(
        self,
        light: int,
        arc: int,
        color: ColorMode = "rgbw",
        intensity: FixtureIntensity = (255.0, 255.0, 255.0),
    ) -> Self:
        raise NotImplementedError()

    def clear_horizontal_arc(
        self,
        light: int,
        arc: int,
        color: ColorMode = "rgbw",
    ) -> Self:
        return self.set_horizontal_arc(light, arc, color, (0, 0, 0))

    turn_on_horizontal_arc = set_horizontal_arc
    turn_off_horizontal_arc = clear_horizontal_arc

    def append_frame(self) -> Self:
        """
        Commits the current state as a frame and appends it to the sequence.

        Further edits after this will modify the next frame.
        Additionally, if `auto_clear` is set to `True`, the next frame is cleared (all off) after appending.
        """
        frame = StageFrame(
            # python is a fake language
            white_fixtures=copy.deepcopy(self._current_white),
            rgb_fixtures=copy.deepcopy(self._current_rgb),
        )
        self.frames.append(frame)

        if self.auto_clear:
            self.turn_off_lightstage()

        return self

    def build(self) -> PlaybackSequence:
        """Builds and returns the playback sequence."""
        return PlaybackSequence(
            name=self.name, capture_hz=self.capture_hz, frames=list(self.frames)
        )

    @classmethod
    def from_sequence(
        cls, sequence: PlaybackSequence, auto_clear: bool = False
    ) -> "SequenceBuilder":
        """
        Creates a builder from an existing playback sequence.

        Existing frames are copied into the builder, further edits will be appended to the sequence.
        Modifying existing frames is not yet supported.
        """
        num_arcs = 12
        lights_per_arc = 14
        if sequence.frames:
            # infer dimensions from previous sequence, should they differ
            num_arcs = len(sequence.frames[0].white_fixtures)
            lights_per_arc = len(sequence.frames[0].white_fixtures[0])

        builder = cls(
            name=sequence.name,
            capture_hz=sequence.capture_hz,
            num_arcs=num_arcs,
            lights_per_arc=lights_per_arc,
            auto_clear=auto_clear,
        )

        builder.frames = list(sequence.frames)
        if sequence.frames:
            last = sequence.frames[-1]
            if not auto_clear:
                builder._current_white = copy.deepcopy(last.white_fixtures)
                builder._current_rgb = copy.deepcopy(last.rgb_fixtures)

        return builder
