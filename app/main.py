from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import API_PREFIX, Settings
from app.db import init_db
from app.errors import register_error_handlers
from app.routers import auth, settings, users


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or Settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(config)
        yield

    app = FastAPI(title="POS Metropolitano API", version="0.1.0", lifespan=lifespan)
    app.state.settings = config
    register_error_handlers(app)

    if config.cors_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.cors_origin_list,
            allow_credentials=True,  # the web app authenticates with a cookie
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/health", include_in_schema=False)
    def health() -> dict:
        return {"status": "ok"}

    for module in (auth, settings, users):
        app.include_router(module.router, prefix=API_PREFIX)
    return app


app = create_app()
