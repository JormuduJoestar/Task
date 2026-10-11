"""Вебхук банка: смена статуса, запрещённые переходы, подпись."""

import hmac
import itertools
import json
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings

STATUSES = ["pending", "succeeded", "failed", "refunded"]
# Эталон допустимых переходов записан независимо от таблицы в приложении.
ALLOWED = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}


def send_webhook(client, payment_id, status):
    return client.post("/webhooks/bank", json={"payment_id": payment_id, "status": status})


@pytest.mark.parametrize(("old", "new"), list(itertools.product(STATUSES, STATUSES)))
def test_transition_matrix(client, create_payment, db, old, new):
    payment_id = create_payment().json()["id"]
    db.set_status(payment_id, old)  # исходное состояние ставим напрямую в БД

    response = send_webhook(client, payment_id, new)

    if (old, new) in ALLOWED:
        assert response.status_code == 200
        assert response.json() == {"result": "ok"}
        assert db.get_payment(payment_id).status == new
    else:
        assert response.status_code == 409
        assert response.json() == {"error": "invalid_transition"}
        assert db.get_payment(payment_id).status == old


def test_forbidden_transition_keeps_status_visible_in_api(client, create_payment):
    payment_id = create_payment().json()["id"]
    assert send_webhook(client, payment_id, "refunded").status_code == 409
    assert client.get(f"/payments/{payment_id}").json()["status"] == "pending"


def test_full_lifecycle_pending_succeeded_refunded(client, create_payment):
    payment_id = create_payment().json()["id"]

    assert send_webhook(client, payment_id, "succeeded").json() == {"result": "ok"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "succeeded"

    assert send_webhook(client, payment_id, "refunded").json() == {"result": "ok"}
    assert client.get(f"/payments/{payment_id}").json()["status"] == "refunded"

    # Из refunded выхода нет.
    assert send_webhook(client, payment_id, "succeeded").status_code == 409
    assert client.get(f"/payments/{payment_id}").json()["status"] == "refunded"


def test_webhook_for_missing_payment_returns_404(client):
    response = send_webhook(client, "00000000-0000-4000-8000-000000000000", "succeeded")
    assert response.status_code == 404


def test_webhook_unknown_status_returns_422(client, create_payment, db):
    payment_id = create_payment().json()["id"]
    response = send_webhook(client, payment_id, "paid")
    assert response.status_code == 422
    assert db.get_payment(payment_id).status == "pending"


def test_webhook_missing_fields_return_422(client):
    assert client.post("/webhooks/bank", json={"status": "succeeded"}).status_code == 422
    assert client.post("/webhooks/bank", json={"payment_id": "x"}).status_code == 422


# ---------------------------------------------------------------- подпись (бонус)

SECRET = "test-secret"


@pytest.fixture
def signed_client(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, SECRET))) as client:
        yield client


def new_payment_id(client):
    tariff_id = client.get("/tariffs").json()[0]["id"]
    body = {"tariff_id": tariff_id, "email": "a@example.com", "method": "card"}
    return client.post("/payments", json=body).json()["id"]


def signed_post(client, payload, signature):
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Signature"] = signature
    return client.post("/webhooks/bank", content=body, headers=headers)


def sign(payload, secret=SECRET):
    return hmac.new(secret.encode(), json.dumps(payload).encode(), sha256).hexdigest()


def test_valid_signature_is_accepted(signed_client):
    payload = {"payment_id": new_payment_id(signed_client), "status": "succeeded"}
    response = signed_post(signed_client, payload, sign(payload))
    assert response.status_code == 200
    assert response.json() == {"result": "ok"}


def test_wrong_signature_returns_401_and_status_unchanged(signed_client):
    payment_id = new_payment_id(signed_client)
    payload = {"payment_id": payment_id, "status": "succeeded"}

    response = signed_post(signed_client, payload, sign(payload, secret="other-secret"))

    assert response.status_code == 401
    assert signed_client.get(f"/payments/{payment_id}").json()["status"] == "pending"


def test_missing_signature_returns_401(signed_client):
    payload = {"payment_id": new_payment_id(signed_client), "status": "succeeded"}
    assert signed_post(signed_client, payload, None).status_code == 401


def test_signature_of_other_body_returns_401(signed_client):
    payment_id = new_payment_id(signed_client)
    signed_payload = {"payment_id": payment_id, "status": "failed"}
    sent_payload = {"payment_id": payment_id, "status": "succeeded"}
    assert signed_post(signed_client, sent_payload, sign(signed_payload)).status_code == 401


def test_non_ascii_signature_returns_401_not_500(signed_client):
    payload = {"payment_id": new_payment_id(signed_client), "status": "succeeded"}
    # httpx принимает не-ASCII значение заголовка только как bytes.
    response = signed_post(signed_client, payload, "подпись".encode())
    assert response.status_code == 401
