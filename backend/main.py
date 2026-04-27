"""Anamnesis FastAPI application entrypoint."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router as api_router
from mcp_server.server import router as mcp_router

app = FastAPI(title="Anamnesis", version="0.0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(mcp_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "anamnesis"}
