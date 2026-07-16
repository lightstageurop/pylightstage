import time
from pylightstage import LightStageSyncClient


def main():
    print("Connecting to LightStage...")
    with LightStageSyncClient() as client:

        print("Turn on stage: red")
        client.turn_on_lightstage(color='rgb', intensity=(255.0, 0.0, 0.0))
        time.sleep(1)

        print("Turn on stage: blue")
        client.turn_on_lightstage(color='rgb', intensity=(0.0, 0.0, 255.0))
        time.sleep(1)

        print("Turn on stage: warm white")
        client.turn_on_lightstage(color='w', intensity=(255.0, 0.0, 0.0))
        time.sleep(1)

        print("Turn on stage: cool white")
        client.turn_on_lightstage(color='w', intensity=(0.0, 0.0, 255.0))
        time.sleep(1)

        print("Turn off stage.")
        client.turn_off_lightstage(color='rgbw')


if __name__ == "__main__":
    main()
