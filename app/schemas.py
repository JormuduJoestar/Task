"""Pydantic-схемы запросов и ответов."""

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

from app.domain import (
    INSTALLMENT_MONTHS,
    PROMO_CODES,
    PaymentMethod,
    PaymentStatus,
    normalize_promo_code,
)


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int  # копейки


class PaymentCreate(BaseModel):
    tariff_id: int
    email: EmailStr
    method: PaymentMethod
    installment_months: int | None = None
    promo_code: str | None = None

    @field_validator("promo_code")
    @classmethod
    def _check_promo_code(cls, value: str | None) -> str | None:
        # Регистр не важен, пустая строка = «не передан», неизвестный код = 422.
        normalized = normalize_promo_code(value)
        if normalized is not None and normalized not in PROMO_CODES:
            raise ValueError("unknown promo code")
        return normalized

    @model_validator(mode="after")
    def _check_installment(self) -> Self:
        if self.method == PaymentMethod.INSTALLMENT:
            if self.installment_months is None:
                raise ValueError("installment_months is required for installment")
            if self.installment_months not in INSTALLMENT_MONTHS:
                allowed = ", ".join(str(m) for m in INSTALLMENT_MONTHS)
                raise ValueError(f"installment_months must be one of: {allowed}")
        elif self.installment_months is not None:
            raise ValueError("installment_months is allowed only for installment method")
        return self


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: PaymentStatus
    tariff_id: int
    amount: int  # копейки, уже со скидкой
    discount: int  # копейки
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None  # копейки
    email: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        # SQLite не хранит часовой пояс: считаем наивное время UTC.
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class WebhookIn(BaseModel):
    payment_id: str
    status: PaymentStatus


class WebhookOut(BaseModel):
    result: Literal["ok"]


class ErrorOut(BaseModel):
    error: str
