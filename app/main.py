"""Точка входа: фабрика приложения и обработчики ошибок."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app import models  # noqa: F401  (регистрирует таблицы в Base.metadata)
from app.config import Settings, load_settings
from app.database import Base, make_engine, make_session_factory
from app.routers import payments, tariffs, webhooks
from app.services import InvalidTransitionError, seed_tariffs

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение. Тесты передают свои настройки (отдельная БД на тест)."""
    settings = settings or load_settings()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        Base.metadata.create_all(engine)
        seed_tariffs(session_factory)
        if settings.webhook_secret is None:
            logger.warning("WEBHOOK_SECRET не задан: подпись вебхуков не проверяется")
        yield
        engine.dispose()

    app = FastAPI(title="Квитто: API платежей", version="1.0.0", lifespan=lifespan)
    app.state.session_factory = session_factory
    app.state.webhook_secret = settings.webhook_secret

    app.include_router(tariffs.router)
    app.include_router(payments.router)
    app.include_router(webhooks.router)

    @app.exception_handler(InvalidTransitionError)
    async def invalid_transition_handler(
        request: Request, exc: InvalidTransitionError
    ) -> JSONResponse:
        # Тело именно {"error": "invalid_transition"}, а не {"detail": ...}.
        return JSONResponse(status_code=409, content={"error": "invalid_transition"})

    return app


app = create_app()
