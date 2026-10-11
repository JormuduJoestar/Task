"""Общие фикстуры.

Каждый тест получает своё приложение и свою SQLite-базу во временной папке,
поэтому тесты не влияют друг на друга. Клиент создаётся через `with`,
иначе не сработает lifespan и тарифы не будут созданы.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import func, select, update

from app.config import Settings
from app.main import create_app
from app.models import Payment

PaymentFactory = Callable[..., Response]


def make_settings(tmp_path: Path, webhook_secret: str | None = None) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        webhook_secret=webhook_secret,
    )


class DbHelper:
    """Прямой доступ к БД из тестов: проверяем состояние, а не только ответы API."""

    def __init__(self, app: FastAPI) -> None:
        self._factory = app.state.session_factory

    def count_payments(self) -> int:
        with self._factory() as db:
            return db.scalar(select(func.count()).select_from(Payment)) or 0

    def get_payment(self, payment_id: str) -> Payment | None:
        with self._factory() as db:
            return db.get(Payment, payment_id)

    def set_status(self, payment_id: str, status: str) -> None:
        with self._factory() as db:
            db.execute(update(Payment).where(Payment.id == payment_id).values(status=status))
            db.commit()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


@pytest.fixture
def fastapi_app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(fastapi_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(fastapi_app) as test_client:
        yield test_client


@pytest.fixture
def db(fastapi_app: FastAPI, client: TestClient) -> DbHelper:
    # Зависит от client: к этому моменту lifespan уже создал таблицы.
    return DbHelper(fastapi_app)


@pytest.fixture
def tariff_ids(client: TestClient) -> dict[str, int]:
    return {t["title"]: t["id"] for t in client.get("/tariffs").json()}


@pytest.fixture
def create_payment(client: TestClient, tariff_ids: dict[str, int]) -> PaymentFactory:
    def _create(
        tariff: str = "standard",
        method: str = "card",
        email: str = "student@example.com",
        promo_code: str | None = None,
        installment_months: int | None = None,
        idempotency_key: str | None = None,
    ) -> Response:
        body: dict = {"tariff_id": tariff_ids[tariff], "email": email, "method": method}
        if promo_code is not None:
            body["promo_code"] = promo_code
        if installment_months is not None:
            body["installment_months"] = installment_months
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key is not None else {}
        return client.post("/payments", json=body, headers=headers)

    return _create
