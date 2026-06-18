from db.models import Base
from db.session import AsyncSessionLocal, engine, get_session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


__all__ = [
    "AsyncSessionLocal",
    "Base",
    "engine",
    "get_session",
    "init_db",
]
