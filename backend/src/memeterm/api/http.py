from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from memeterm import __version__
from memeterm.api import debug, health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Subsystem task groups will be attached here in Phase 2+.
    yield


app = FastAPI(
    title="memeterm API",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(debug.router, prefix="/api")


@app.get("/")
async def root() -> dict[str, str]:
    return {"name": "memeterm", "version": __version__}
