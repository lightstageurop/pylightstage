"""
Basic usage, with synchronous client.

This wrapper runs an asyncio event loop in a background thread,
allowing you to write normal blocking (sync) code.
This could be useful for older Jupyter Notebooks
and legacy codebases where asyncio.run() isn't available.

This shouldn't be neccessary for newer Jupyter Notebooks,
as they support top level await. See 20_notebook.ipynb for an example.
"""

import time

from pylightstage import LightStageSyncClient

# WebSocket endpoint
URI = "ws://172.30.40.238:8080/ws"


def main():
    print("Connecting to LightStage...")

    # The `with` syntax is equivalent to running .open() and then .close().
    with LightStageSyncClient(uri=URI) as client:
        print("Turn on stage: red")
        client.turn_on_lightstage(color="rgb", intensity=(255.0, 0.0, 0.0))
        time.sleep(1)

        print("Turn on stage: blue")
        client.turn_on_lightstage(color="rgb", intensity=(0.0, 0.0, 255.0))
        time.sleep(1)

        print("Turn on stage: warm white")
        client.turn_on_lightstage(color="w", intensity=(255.0, 0.0, 0.0))
        time.sleep(1)

        print("Turn on stage: all on")
        client.turn_on_lightstage(color="rgbw", intensity=(255.0, 255.0, 255.0))
        time.sleep(1)

        print("Triggering cameras..")
        client.trigger()
        time.sleep(1)

        print("Turn off stage.")
        client.turn_off_lightstage(color="rgbw")


# main guard
if __name__ == "__main__":
    # no asyncio.run() needed this time
    main()
