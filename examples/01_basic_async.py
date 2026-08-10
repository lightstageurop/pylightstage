"""
Basic usage.

This cycles through a couple colours, captures one frame,
then turns the lights off again.
"""

import asyncio

from pylightstage import LightStageClient

# WebSocket endpoint
# Should be ws://serverip:8080/ws
URI = "ws://10.37.211.100:8080/ws"


async def main():
    print("Connecting to LightStage...")

    # Opens the connection to the Light Stage server running on the Raspberry Pi.
    # This uses an asynchronous implementation of websockets under the hood,
    # hence the need for `async with`.
    async with LightStageClient(uri=URI) as client:
        # --- Manual Mode operation ---
        # Sending direct fixture commands places the light stage into manual mode.
        # The server will continue refreshing the lights by sending DMX packets
        # at a fixed interval, so the current state is maintained.
        # However, the fixtures remain static until another command is sent,
        # or the light stage is switched to a different operating mode.

        # Set all RGB fixtures to full intensity red.
        print("Turn on stage: red")
        # Note intensity=(r, g, b)
        await client.turn_on_lightstage(color="rgb", intensity=(255.0, 0.0, 0.0))
        await asyncio.sleep(1)

        # Then blue
        print("Turn on stage: blue")
        await client.turn_on_lightstage(color="rgb", intensity=(0.0, 0.0, 255.0))
        await asyncio.sleep(1)

        # Then warm white
        print("Turn on stage: warm white")
        # Note intensity=(warm, neutral, cool)
        await client.turn_on_lightstage(color="w", intensity=(255.0, 0.0, 0.0))
        await asyncio.sleep(1)

        # Turn on all channels full intensity (rgb + w)
        print("Turn on stage: all on")
        # note color='rgbw'
        await client.turn_on_lightstage(color="rgbw", intensity=(255.0, 255.0, 255.0))
        await asyncio.sleep(1)

        # Trigger connected DSLRs using RPi GPIOs.
        # In manual mode, _you_ must tell the light stage when to capture a frame.
        print("Triggering cameras..")
        await client.trigger()
        await asyncio.sleep(1)

        # Finally turn off all fixtures (rgb + w)
        print("Turn off stage.")
        await client.turn_off_lightstage(color="rgbw")


# Run the script only when this file is executed directly
if __name__ == "__main__":
    # Start async event loop.
    # This will not work if another event loop is already running, eg. in jupyter notebooks
    asyncio.run(main())
