"""Anamnesis FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from db import init_db
from mcp_server.server import mcp


@asynccontextmanager
async def lifespan(app: FastAPI):
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "anamnesis"}


app.mount("/", mcp.streamable_http_app())
