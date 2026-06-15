from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.app.api.routes import router
from backend.app.config import get_settings
from backend.app.db.session import SessionLocal
from backend.app.db.startup import create_schema
from backend.app.seed import seed_demo_cases

settings = get_settings()


def prepare_database() -> None:
    if not settings.run_db_startup:
        return
    create_schema()
    if settings.seed_demo_data:
        with SessionLocal() as session:
            seed_demo_cases(session, settings.upload_dir)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    prepare_database()
    yield


app = FastAPI(title="Alcohol Label Verifier", lifespan=lifespan)
app.include_router(router)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok"}


if settings.static_dir.exists():
    app.mount("/", StaticFiles(directory=settings.static_dir, html=True), name="frontend")
