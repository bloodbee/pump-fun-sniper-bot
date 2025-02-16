import asyncio
import traceback
import os
from dotenv import load_dotenv

from src.bot import Bot
from src.storage import Storage

load_dotenv()

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL"))


async def main():
    storage = Storage()
    storage.load()
    bot = Bot(storage=storage, is_rpc=False)

    while True:
        try:
            await bot.run()
        except Exception as e:
            traceback.print_exc()
            print(f"[ERROR] WebSocket connection lost: {e}. Reconnecting ...")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
