"""Настройки приложения из переменных окружения."""

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///./kvitto.db"


@dataclass(frozen=True)
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    # Если секрет не задан, проверка подписи вебхука отключена.
    webhook_secret: str | None = None


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL,
        webhook_secret=os.environ.get("WEBHOOK_SECRET") or None,
    )
