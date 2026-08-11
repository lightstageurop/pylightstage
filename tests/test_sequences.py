"""
tests/test_sequences.py

Tests playback sequence models, serialization, and sequence builder behavior.
"""

import pytest

from pylightstage.models import PlaybackSequence, SequenceSummary, StageFrame
from pylightstage.sequences import SequenceBuilder

pytestmark = pytest.mark.unit


def test_stage_frame_to_dict_roundtrip():
    frame = StageFrame(
        white_fixtures=[[(1, 2, 3), (4, 5, 6)]],
        rgb_fixtures=[[(7, 8, 9), (10, 11, 12)]],
    )

    data = frame.to_dict()
    restored = StageFrame.from_dict(data)

    assert restored == frame


def test_stage_frame_from_dict_normalises_inner_values_to_tuples():
    data = {
        "white_fixtures": [[[1, 2, 3], [4, 5, 6]]],
        "rgb_fixtures": [[[7, 8, 9], [10, 11, 12]]],
    }

    frame = StageFrame.from_dict(data)

    assert frame.white_fixtures == [[(1, 2, 3), (4, 5, 6)]]
    assert frame.rgb_fixtures == [[(7, 8, 9), (10, 11, 12)]]
    assert isinstance(frame.white_fixtures[0][0], tuple)
    assert isinstance(frame.rgb_fixtures[0][0], tuple)


def test_playback_sequence_total_frames():
    frame = StageFrame()
    sequence = PlaybackSequence(
        name="test",
        capture_hz=20.0,
        frames=[frame, frame, frame, frame],
    )

    assert sequence.total_frames == 4


def test_playback_sequence_duration_secs():
    sequence = PlaybackSequence(
        name="test",
        capture_hz=20.0,
        frames=[StageFrame(), StageFrame(), StageFrame(), StageFrame()],
    )

    assert sequence.duration_secs == 0.2


def test_playback_sequence_duration_secs_is_zero_when_capture_hz_is_zero():
    sequence = PlaybackSequence(
        name="test",
        capture_hz=0.0,
        frames=[StageFrame()],
    )

    assert sequence.duration_secs == 0.0


def test_playback_sequence_to_summary():
    sequence = PlaybackSequence(
        name="demo",
        capture_hz=10.0,
        frames=[StageFrame(), StageFrame(), StageFrame()],
    )

    summary = sequence.to_summary(seq_id="01KYSXPXCDVX7YH4F4GT1FM065")

    assert summary == SequenceSummary(
        id="01KYSXPXCDVX7YH4F4GT1FM065",
        name="demo",
        capture_hz=10.0,
        total_frames=3,
        duration_secs=0.3,
    )


def test_playback_sequence_to_dict_roundtrip():
    sequence = PlaybackSequence(
        name="roundtrip",
        capture_hz=30.0,
        frames=[
            StageFrame(
                white_fixtures=[[(1, 2, 3)]],
                rgb_fixtures=[[(4, 5, 6)]],
            )
        ],
    )

    data = sequence.to_dict()
    restored = PlaybackSequence.from_dict(data)

    assert restored == sequence


def test_playback_sequence_to_cbor_roundtrip():
    sequence = PlaybackSequence(
        name="cbor",
        capture_hz=24.0,
        frames=[
            StageFrame(
                white_fixtures=[[(11, 22, 33)]],
                rgb_fixtures=[[(44, 55, 66)]],
            )
        ],
    )

    payload = sequence.to_cbor()
    restored = PlaybackSequence.from_cbor(payload)

    assert restored == sequence


def test_playback_sequence_from_cbor_rejects_non_dict_payload():
    import cbor2

    payload = cbor2.dumps([1, 2, 3])

    with pytest.raises(ValueError, match="Invalid CBOR payload"):
        PlaybackSequence.from_cbor(payload)


def test_playback_sequence_save_and_load_cbor(tmp_path):
    sequence = PlaybackSequence(
        name="save_raw",
        capture_hz=15.0,
        frames=[
            StageFrame(
                white_fixtures=[[(1, 1, 1)]],
                rgb_fixtures=[[(2, 2, 2)]],
            )
        ],
    )

    path = tmp_path / "sequence.cbor"
    sequence.save(path)

    loaded = PlaybackSequence.load(path)

    assert loaded == sequence


def test_playback_sequence_save_and_load_compressed_cbor(tmp_path):
    sequence = PlaybackSequence(
        name="save_zst",
        capture_hz=15.0,
        frames=[
            StageFrame(
                white_fixtures=[[(3, 3, 3)]],
                rgb_fixtures=[[(4, 4, 4)]],
            )
        ],
    )

    path = tmp_path / "sequence.cbor.zst"
    sequence.save(path)

    loaded = PlaybackSequence.load(path)

    assert loaded == sequence


def test_sequence_builder_build_returns_playback_sequence():
    builder = SequenceBuilder(name="builder_test", capture_hz=12.5)
    builder.append_frame()

    sequence = builder.build()

    assert isinstance(sequence, PlaybackSequence)
    assert sequence.name == "builder_test"
    assert sequence.capture_hz == 12.5
    assert len(sequence.frames) == 1


@pytest.mark.parametrize("capture_hz", [0.0, -1.0, float("nan"), float("inf")])
def test_sequence_builder_rejects_invalid_capture_rate(capture_hz):
    with pytest.raises(ValueError, match="positive finite"):
        SequenceBuilder(name="invalid", capture_hz=capture_hz)


def test_sequence_builder_set_light_updates_rgb_and_white_for_rgbw():
    builder = SequenceBuilder(name="rgbw", num_arcs=1, lights_per_arc=1)

    returned = builder.set_light(0, 0, color="rgbw", intensity=(255.0, 128.0, 0.0))

    assert returned is builder
    assert builder._current_rgb[0][0] == (65535, 32896, 0)
    assert builder._current_white[0][0] == (65535, 32896, 0)


def test_sequence_builder_set_light_updates_only_rgb_when_color_is_rgb():
    builder = SequenceBuilder(name="rgb", num_arcs=1, lights_per_arc=1)

    builder.set_light(0, 0, color="rgb", intensity=(255.0, 0.0, 0.0))

    assert builder._current_rgb[0][0] == (65535, 0, 0)
    assert builder._current_white[0][0] == (0, 0, 0)


def test_sequence_builder_set_light_updates_only_white_when_color_is_w():
    builder = SequenceBuilder(name="w", num_arcs=1, lights_per_arc=1)

    builder.set_light(0, 0, color="w", intensity=(10.0, 20.0, 30.0))

    assert builder._current_rgb[0][0] == (0, 0, 0)
    assert builder._current_white[0][0] != (0, 0, 0)


def test_sequence_builder_clear_light_turns_fixture_off():
    builder = SequenceBuilder(name="clear", num_arcs=1, lights_per_arc=1)
    builder.set_light(0, 0, intensity=(255.0, 255.0, 255.0))

    returned = builder.clear_light(0, 0)

    assert returned is builder
    assert builder._current_rgb[0][0] == (0, 0, 0)
    assert builder._current_white[0][0] == (0, 0, 0)


def test_sequence_builder_alias_methods_match_new_names():
    builder = SequenceBuilder(name="aliases", num_arcs=1, lights_per_arc=2)

    builder.turn_on_light(1, 0, color="rgb", intensity=(255.0, 0.0, 0.0))
    assert builder._current_rgb[0][1] == (65535, 0, 0)

    builder.turn_off_light(1, 0, color="rgb")
    assert builder._current_rgb[0][1] == (0, 0, 0)


def test_sequence_builder_set_arc_updates_entire_arc():
    builder = SequenceBuilder(name="arc", num_arcs=1, lights_per_arc=3)

    builder.set_arc(0, color="rgb", intensity=(0.0, 255.0, 0.0))

    assert builder._current_rgb[0] == [
        (0, 65535, 0),
        (0, 65535, 0),
        (0, 65535, 0),
    ]


def test_sequence_builder_set_lightstage_updates_all_arcs():
    builder = SequenceBuilder(name="stage", num_arcs=2, lights_per_arc=2)

    builder.set_lightstage(color="rgb", intensity=(0.0, 0.0, 255.0))

    assert builder._current_rgb == [
        [(0, 0, 65535), (0, 0, 65535)],
        [(0, 0, 65535), (0, 0, 65535)],
    ]


@pytest.mark.parametrize(
    ("arc", "light", "pol", "expected_channels"),
    [
        (0, 0, "up", {"rgb", "white"}),
        (0, 0, "pp", {"rgb"}),
        (0, 0, "cp", {"white"}),
        (1, 0, "pp", {"white"}),
        (0, 1, "pp", {"white"}),
    ],
)
def test_sequence_builder_set_pol_light_selects_physical_channel(
    arc, light, pol, expected_channels
):
    builder = SequenceBuilder(name="polarized", num_arcs=2, lights_per_arc=2)

    returned = builder.set_pol_light(light, arc, pol=pol, intensity=(255.0, 0.0, 0.0))

    active_channels = {
        channel
        for channel, value in (
            ("rgb", builder._current_rgb[arc][light]),
            ("white", builder._current_white[arc][light]),
        )
        if value != (0, 0, 0)
    }
    assert returned is builder
    assert active_channels == expected_channels


def test_sequence_builder_clear_pol_light_clears_selected_channel():
    builder = SequenceBuilder(name="polarized-clear", num_arcs=1, lights_per_arc=1)
    builder.set_pol_light(0, 0, pol="pp", intensity=(255.0, 0.0, 0.0))

    returned = builder.turn_off_pol_light(0, 0, pol="pp")

    assert returned is builder
    assert builder._current_rgb[0][0] == (0, 0, 0)


def test_sequence_builder_horizontal_arc_updates_and_clears_every_arc():
    builder = SequenceBuilder(name="horizontal", num_arcs=3, lights_per_arc=2)

    returned = builder.turn_on_horizontal_arc(
        1, color="rgb", intensity=(0.0, 255.0, 0.0)
    )

    assert returned is builder
    assert [arc[1] for arc in builder._current_rgb] == [(0, 65535, 0)] * 3
    assert [arc[0] for arc in builder._current_rgb] == [(0, 0, 0)] * 3

    builder.turn_off_horizontal_arc(1, color="rgb")
    assert [arc[1] for arc in builder._current_rgb] == [(0, 0, 0)] * 3


def test_sequence_builder_append_frame_snapshots_current_state():
    builder = SequenceBuilder(name="snapshot", num_arcs=1, lights_per_arc=1)
    builder.set_light(0, 0, color="rgb", intensity=(255.0, 0.0, 0.0))

    builder.append_frame()
    frame = builder.frames[-1]
    builder.clear_light(0, 0, color="rgb")

    assert frame.rgb_fixtures == [[(65535, 0, 0)]]
    assert builder.frames[0].rgb_fixtures == [[(65535, 0, 0)]]
    assert builder._current_rgb[0][0] == (0, 0, 0)


def test_sequence_builder_append_frame_auto_clear_resets_state_after_append():
    builder = SequenceBuilder(
        name="autoclear", num_arcs=1, lights_per_arc=1, auto_clear=True
    )
    builder.set_light(0, 0, intensity=(255.0, 255.0, 255.0))

    builder.append_frame()
    frame = builder.frames[-1]

    assert frame.white_fixtures == [[(65535, 65535, 65535)]]
    assert frame.rgb_fixtures == [[(65535, 65535, 65535)]]
    assert builder._current_white[0][0] == (0, 0, 0)
    assert builder._current_rgb[0][0] == (0, 0, 0)


def test_sequence_builder_set_light_rejects_invalid_arc():
    builder = SequenceBuilder(name="invalid_arc", num_arcs=1, lights_per_arc=1)

    with pytest.raises(IndexError, match="arc index"):
        builder.set_light(0, 1)


def test_sequence_builder_set_light_rejects_invalid_light():
    builder = SequenceBuilder(name="invalid_light", num_arcs=1, lights_per_arc=1)

    with pytest.raises(IndexError, match="light index"):
        builder.set_light(1, 0)
