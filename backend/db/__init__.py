from db.models import Base, LLMCall, PipelineRun
from db.session import AsyncSessionLocal, engine


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


__all__ = [
    "AsyncSessionLocal",
    "Base",
    "LLMCall",
    "PipelineRun",
    "engine",
    "init_db",
]
