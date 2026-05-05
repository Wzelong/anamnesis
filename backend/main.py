"""Anamnesis FastAPI application entrypoint."""
import logging
import os
from contextlib import asynccontextmanager

os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_XET"] = "1"
os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.chat_routes import router as chat_router
from api.routes import router as api_router
from config import settings
from db import init_db
from mcp_server.server import mcp

for _name in ("httpx", "mcp", "sentence_transformers", "faiss", "faiss.loader"):
    logging.getLogger(_name).setLevel(logging.ERROR)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

log = logging.getLogger("anamnesis")


def _warmup_coding() -> None:
    if not settings.warmup_coding_on_startup:
        log.info("Coding warmup disabled.")
        return

    from core.coding import warmup

    log.info("Warming coding model and indexes...")
    result = warmup()
    loaded = ", ".join(
        f"{system}={count:,}" for system, count in result.loaded_indexes.items()
    )
    if result.missing_indexes:
        log.warning(
            "Coding warmup missing indexes: %s. Pipeline runs that hit these "
            "systems will fail until the indexes are seeded under %s.",
            ", ".join(result.missing_indexes),
            os.environ.get("ANAMNESIS_INDEX_DIR", "data/indexes"),
        )
    log.info("Coding model and indexes ready%s.", f": {loaded}" if loaded else "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Starting.")
    _warmup_coding()
    await init_db()
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Anamnesis", version="0.0.1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(chat_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "anamnesis"}


app.mount("/", mcp.streamable_http_app())
