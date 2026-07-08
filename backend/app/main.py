from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import evaluations, health, repos, runs
from app.core.config import settings
from app.core.database import init_db


def create_app() -> FastAPI:
    app = FastAPI(title="CodeMate API", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(repos.router)
    app.include_router(runs.router)
    app.include_router(evaluations.router)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    return app


app = create_app()
