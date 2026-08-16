"""
Handling server events.

Communication with the LightStage server is asynchronous and event-driven.
While you can send commands and await their responses, the server can also
broadcast events at any time (for example, `ModeChanged` or
`CaptureFinished`).

This example demonstrates two ways to handle these events:
1. Register a persistent callback with `@client.on_event`.
2. Wait for a specific event using `wait_for_event()`.
"""

import asyncio

from pylightstage import LightStageClient

# WebSocket endpoint
URI = "ws://172.30.40.238:8080/ws"


async def main():
    print("Connecting to LightStage...")

    async with LightStageClient(uri="ws://172.30.40.238:8080/ws") as client:
        # --- Register a callback
        # Called whenever the server broadcasts an event.
        @client.on_event
        def log_event(event):
            print(f"[Callback] Received event: {event}")

        print("Changing stage mode to 'Manual'...")
        await client.set_mode_manual()
        await asyncio.sleep(1)

        print("Starting OLAT sequence...")
        await client.set_mode_olat(30.0)
        await asyncio.sleep(1)

        # --- Blocking wait for an event
        # Wait until the OLAT sequence finishes.
        print("Waiting for 'CaptureFinished'...")
        try:
            capture_event = await client.wait_for_event(
                "CaptureFinished",
                timeout=20.0,  # Use timeout=None to wait indefinitely.
            )
            print(f"OLAT complete: {capture_event}")

        except TimeoutError:
            print("Timed out waiting for 'CaptureFinished'.")

        # Continue listening for background events forever, or until server connection fails.
        print("Listening for further events. Press Ctrl+C to exit.")
        await client.wait_until_disconnected()

    print("Connection closed. Goodbye.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
