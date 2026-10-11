"""Проверка подписи вебхука банка."""

import hashlib
import hmac
from typing import Annotated

from fastapi import Header, HTTPException, Request


def compute_signature(secret: str, body: bytes) -> str:
    """HMAC-SHA256 от сырого тела запроса, hex-строка в нижнем регистре."""
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def verify_signature(
    request: Request,
    x_signature: Annotated[str | None, Header()] = None,
) -> None:
    """Зависимость: 401, если подпись неверна. Без WEBHOOK_SECRET проверка выключена."""
    secret: str | None = request.app.state.webhook_secret
    if not secret:
        return
    body = await request.body()
    expected = compute_signature(secret, body)
    received = (x_signature or "").strip().lower()
    # Сравниваем байты: compare_digest для str с не-ASCII символами падает с TypeError.
    if not hmac.compare_digest(expected.encode(), received.encode()):
        raise HTTPException(status_code=401, detail="Invalid signature")
