"""SQLAlchemy 2.0 async engine and session factory."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from config import settings

# asyncpg connections are bound to the event loop that created them. The server
# inits the schema on one loop and serves requests on another, so a pooled
# connection would be reused across loops ("Future attached to a different loop").
# NullPool opens a fresh connection per use on the current loop — also the right
# choice for Neon's pooled (pgBouncer) endpoint, which already pools server-side.
_engine_kwargs: dict = {"echo": False, "future": True}
if settings.database_url.startswith("postgresql"):
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.database_url, **_engine_kwargs)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
