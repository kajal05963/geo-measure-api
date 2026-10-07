from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.files import router as files_router
from app.db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Geospatial File Measurement API",
    version="1.0.0",
    description="Upload a Shapefile (.zip) or KML and get per-feature area/length measurements.",
    lifespan=lifespan,
)
app.include_router(files_router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}
