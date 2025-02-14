from sqlalchemy.ext.asyncio import AsyncEngine
from src.db import Base
from src.models import User, File, Team, Role, TeamMember


async def init_models(engine: AsyncEngine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
