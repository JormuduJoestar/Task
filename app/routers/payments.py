from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, Response

from app import services
from app.deps import DbSession
from app.domain import PaymentStatus
from app.schemas import PaymentCreate, PaymentOut

router = APIRouter(tags=["payments"])


@router.post(
    "/payments",
    response_model=PaymentOut,
    status_code=201,
    responses={
        200: {"model": PaymentOut, "description": "Платёж с таким Idempotency-Key уже есть"}
    },
)
def create_payment(
    data: PaymentCreate,
    response: Response,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(max_length=255)] = None,
) -> PaymentOut:
    # Пустой заголовок считаем отсутствующим.
    key = idempotency_key.strip() if idempotency_key else None
    try:
        payment, created = services.create_payment(db, data, key or None)
    except services.TariffNotFoundError:
        # Формат совпадает со стандартным ответом 422 от FastAPI.
        raise HTTPException(
            status_code=422,
            detail=[
                {
                    "type": "value_error",
                    "loc": ["body", "tariff_id"],
                    "msg": f"Tariff {data.tariff_id} not found",
                    "input": data.tariff_id,
                }
            ],
        ) from None
    if not created:
        response.status_code = 200
    return PaymentOut.model_validate(payment)


@router.get("/payments", response_model=list[PaymentOut])
def list_payments(
    db: DbSession,
    email: str | None = None,
    status: PaymentStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PaymentOut]:
    payments = services.list_payments(db, email, status, limit, offset)
    return [PaymentOut.model_validate(p) for p in payments]


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: str, db: DbSession) -> PaymentOut:
    payment = services.get_payment(db, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return PaymentOut.model_validate(payment)
