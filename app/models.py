"""Модели базы данных. Все суммы — целые числа в копейках."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(50), unique=True)
    price: Mapped[int] = mapped_column(Integer)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    email: Mapped[str] = mapped_column(String(320), index=True)
    method: Mapped[str] = mapped_column(String(20))
    installment_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[int] = mapped_column(Integer)
    discount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), index=True)
    schedule: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    promo_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # UNIQUE: гарантия идемпотентности на уровне БД. Несколько NULL допустимы.
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
