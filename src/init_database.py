import asyncio
from src.db import engine
from src.init_db import init_models


async def init():
    await init_models(engine)


if __name__ == "__main__":
    asyncio.run(init())
