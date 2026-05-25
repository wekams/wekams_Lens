"""FastAPI application entry point.

Run locally:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api import chat, conversations, health, sources
from app.core.config import settings
from app.core.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log = get_logger(__name__)
    log.info(
        "wekams.startup",
        version=__version__,
        env=settings.env.value,
        llm_provider=settings.llm_provider.value,
    )
    yield
    log.info("wekams.shutdown")


app = FastAPI(
    title="Wekams Lens",
    description="Unified data agent — Community Edition.",
    version=__version__,
    lifespan=lifespan,
)

# Dev CORS — production deployments configure this from the orchestrator's
# environment; the customer-facing UI is typically same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(chat.router)
app.include_router(sources.router)
app.include_router(conversations.router)


@app.get("/")
async def root() -> dict:
    return {
        "name": "wekams-lens",
        "version": __version__,
        "docs": "/docs",
    }
