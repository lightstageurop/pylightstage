"""
Playback mode usage.

This briefly shows how to
- use the SequenceBuilder to create a PlaybackSequence,
- save it locally,
- upload it to the server, and
- play it back on the light stage.
"""

import asyncio
from pathlib import Path

from pylightstage import (
    LightStageClient,
    PlaybackSequence,
    SequenceBuilder,
    SequenceSummary,
)

# Default WebSocket endpoint for a locally running Light Stage server.
SERVER_URI = "ws://127.0.0.1:8080/ws"


def print_summary(summary: SequenceSummary, title: str = "Sequence Summary") -> None:
    """Print a concise summary of a playback sequence."""
    print(f"\n== {title} ==")
    print(f"  ID       : {summary.id}")
    print(f"  Name     : {summary.name}")
    print(f"  Frames   : {summary.total_frames}")
    print(f"  Duration : {summary.duration_secs:.2f}s")


def build_blink_sequence() -> PlaybackSequence:
    """Create a simple sequence that alternates all lights blue/green with a rotating white arc."""
    builder = SequenceBuilder(name="Blinky", capture_hz=30.0)

    for _ in range(5):  # 5 repeats
        for arc in range(12):  # 2 frames for each arc
            _ = (
                builder
                # green frame with one white arc
                .set_lightstage(color="rgb", intensity=(0.0, 255.0, 0.0))
                .set_arc(arc=arc, color="w", intensity=(255.0, 255.0, 255.0))
                .append_frame()  # commit frame
                # blue frame with one white arc
                .set_lightstage(color="rgb", intensity=(0.0, 0.0, 255.0))
                .set_arc(arc=arc, color="w", intensity=(255.0, 255.0, 255.0))
                .append_frame()
            )

            # the braces allow for multi-line sequences like this without having to write
            # builder.this()
            # builder.that()
            # etc.
            # python is a fake language.

    return builder.build()  # return the sequence


async def main() -> None:
    # 1. Create a playback sequence.

    print("[1/3] Building sequence...")
    sequence = build_blink_sequence()

    # 2. Save the sequence locally.

    print("[2/3] Saving sequence...")

    cbor_path = Path("basic_blink.cbor")
    sequence.save(cbor_path)

    # Saving to a ".cbor.zst" path automatically writes a Zstandard-compressed
    # version of the sequence.
    zst_path = Path("basic_blink.cbor.zst")
    sequence.save(zst_path)

    print_summary(sequence.to_summary(), title="Local Sequence")
    print(f"  Saved files: {cbor_path.name}, {zst_path.name}")

    # 3. Upload the sequence, play it, then clean it up.

    print(f"\n[3/3] Connecting to {SERVER_URI}...")

    async with LightStageClient(uri=SERVER_URI) as client:
        # List sequences that are already stored on the server.
        print("\nServer sequences:")
        existing = await client.list_sequences()

        if existing:
            for seq in existing:
                print(
                    f"  - [{seq.id}] {seq.name} ({seq.total_frames} frames, {seq.duration_secs:.2f}s)"
                )
        else:
            print("  (none)")

        # Upload our newly created sequence.
        print(f"\nUploading '{sequence.name}'...")

        # Uploading returns a SequenceSummary for the stored sequence
        # including a server-generated ID
        uploaded = await client.upload_sequence(sequence)

        print(f"  OK  Uploaded as ID {uploaded.id}")
        # we can use this ID to play and delete the sequence

        try:
            # Fetch the server-side summary again, using the ID
            remote = await client.get_sequence(uploaded.id)
            assert remote == uploaded  # this should be identical

            print_summary(remote, title="Remote Sequence")

            # Start the playback sequence.
            print("\nStarting playback...")
            await client.set_mode_playback(uploaded.id)

            # Wait until playback finishes, allowing some margin for the timeout
            timeout = uploaded.duration_secs + 10.0
            await client.wait_for_event("CaptureFinished", timeout=timeout)
            print("  OK  Playback finished.")

        finally:
            # Remove the uploaded sequence
            print(f"\nDeleting remote sequence {uploaded.id}...")
            await client.delete_sequence(uploaded.id)
            print("  OK  Deleted.")

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
