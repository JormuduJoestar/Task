from fastapi import APIRouter, Depends, HTTPException

from app import services
from app.deps import DbSession
from app.schemas import ErrorOut, WebhookIn, WebhookOut
from app.security import verify_signature

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhooks/bank",
    response_model=WebhookOut,
    dependencies=[Depends(verify_signature)],
    responses={409: {"model": ErrorOut, "description": "Запрещённый переход статуса"}},
)
def bank_webhook(payload: WebhookIn, db: DbSession) -> WebhookOut:
    try:
        services.apply_bank_status(db, payload.payment_id, payload.status)
    except services.PaymentNotFoundError:
        raise HTTPException(status_code=404, detail="Payment not found") from None
    return WebhookOut(result="ok")
