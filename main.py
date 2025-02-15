import asyncio
import os
from dotenv import load_dotenv

from src.bot import Bot
from src.storage import Storage

load_dotenv()

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL"))


async def main():
    storage = Storage()
    storage.load()
    bot = Bot(storage)

    while True:
        try:
            await bot.run()
        except Exception as e:
            print(f"[ERROR] WebSocket connection lost: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
