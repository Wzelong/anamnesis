from db.models import AppUser, Base, UsageRun
from db.session import AsyncSessionLocal, engine, get_session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


__all__ = [
    "AppUser",
    "AsyncSessionLocal",
    "Base",
    "UsageRun",
    "engine",
    "get_session",
    "init_db",
]
