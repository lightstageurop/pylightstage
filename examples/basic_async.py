import asyncio
from pylightstage import LightStageClient


async def main():
    print("Connecting to LightStage...")
    async with LightStageClient() as client:

        print("Turn on stage: red")
        await client.turn_on_lightstage(color='rgb', intensity=(255.0, 0.0, 0.0))
        await asyncio.sleep(1)

        print("Turn on stage: blue")
        await client.turn_on_lightstage(color='rgb', intensity=(0.0, 0.0, 255.0))
        await asyncio.sleep(1)

        print("Turn on stage: warm white")
        await client.turn_on_lightstage(color='w', intensity=(255.0, 0.0, 0.0))
        await asyncio.sleep(1)

        print("Turn on stage: cool white")
        await client.turn_on_lightstage(color='w', intensity=(0.0, 0.0, 255.0))
        await asyncio.sleep(1)

        print("Triggering cameras..")
        await client.trigger()
        await asyncio.sleep(1)

        print("Turn off stage.")
        await client.turn_off_lightstage(color='rgbw')

if __name__ == "__main__":
    asyncio.run(main())
