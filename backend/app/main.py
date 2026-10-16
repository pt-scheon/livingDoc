"""Application factory: API + (optionally) the built-in frontend on one port."""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .forecast_api import router as forecast_router
from .config import settings
from .services.seed import init_db
from .workers import Workers

FRONTEND_DIR = Path(os.environ.get("LIVINGDOC_FRONTEND", Path(__file__).resolve().parents[2] / "frontend"))


def create_app(serve_frontend: bool = True) -> FastAPI:
    workers = Workers()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db()
        if settings.background_workers:
            workers.start()
        yield
        workers.stop()

    app = FastAPI(title="LivingDoc API", version="1.0.0", lifespan=lifespan,
                  description="Self-updating business brain: notes and scanner events in, a live document out. Includes the Foresight demand & pricing forecaster under /api/forecast, /api/pricing, /api/factors, /api/scorecard, ...")
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)
    app.include_router(forecast_router)
    if serve_frontend and FRONTEND_DIR.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
    return app


app = create_app()
