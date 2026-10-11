"""Создание и чтение платежей, суммы, график рассрочки, валидация."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

PRICES = {"basic": 990000, "standard": 1990000, "premium": 2990000}
RESPONSE_FIELDS = {
    "id",
    "status",
    "tariff_id",
    "amount",
    "discount",
    "method",
    "installment_months",
    "schedule",
    "email",
    "created_at",
}


def test_tariffs_list(client):
    response = client.get("/tariffs")
    assert response.status_code == 200
    tariffs = response.json()
    assert [(t["title"], t["price"]) for t in tariffs] == list(PRICES.items())
    assert all(set(t) == {"id", "title", "price"} for t in tariffs)
    assert all(type(t["price"]) is int for t in tariffs)
    assert len({t["id"] for t in tariffs}) == 3


def test_tariffs_not_duplicated_on_restart(client, settings):
    # Второе приложение на той же БД: сидинг не должен создавать дубли.
    with TestClient(create_app(settings)) as second:
        assert len(second.get("/tariffs").json()) == 3
    assert len(client.get("/tariffs").json()) == 3


@pytest.mark.parametrize("promo", [None, "KVITTO10", "kvitto10", " KvItTo10 "])
@pytest.mark.parametrize("tariff", list(PRICES))
def test_amount_with_and_without_promo(create_payment, db, tariff, promo):
    price = PRICES[tariff]
    expected_discount = price // 10 if promo else 0

    response = create_payment(tariff=tariff, promo_code=promo)

    assert response.status_code == 201
    body = response.json()
    assert body["discount"] == expected_discount
    assert body["amount"] == price - expected_discount
    assert body["amount"] + body["discount"] == price
    assert type(body["amount"]) is int
    assert type(body["discount"]) is int
    # То же самое лежит в базе.
    row = db.get_payment(body["id"])
    assert (row.amount, row.discount) == (body["amount"], body["discount"])


def test_standard_with_promo_exact_numbers(create_payment):
    body = create_payment(tariff="standard", promo_code="kvitto10").json()
    assert body["discount"] == 199000
    assert body["amount"] == 1791000


def test_new_payment_response_shape(create_payment, tariff_ids):
    response = create_payment(tariff="premium", method="sbp", email="a@example.com")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == RESPONSE_FIELDS  # promo_code и ключ идемпотентности не отдаём
    assert body["status"] == "pending"
    assert body["tariff_id"] == tariff_ids["premium"]
    assert body["method"] == "sbp"
    assert body["email"] == "a@example.com"
    assert body["installment_months"] is None
    assert body["schedule"] is None
    assert datetime.fromisoformat(body["created_at"]).tzinfo is not None


# Эталонные графики записаны вручную, независимо от функции build_schedule.
SCHEDULES = [
    ("standard", None, 3, [663334, 663333, 663333]),
    ("standard", None, 6, [331667] * 4 + [331666] * 2),
    ("standard", None, 12, [165834] * 4 + [165833] * 8),
    ("premium", None, 3, [996667, 996667, 996666]),
    ("premium", None, 6, [498334] * 2 + [498333] * 4),
    ("premium", None, 12, [249167] * 8 + [249166] * 4),
    ("standard", "KVITTO10", 3, [597000] * 3),
    ("basic", None, 12, [82500] * 12),
]


@pytest.mark.parametrize(("tariff", "promo", "months", "expected"), SCHEDULES)
def test_installment_schedule(create_payment, db, tariff, promo, months, expected):
    response = create_payment(
        tariff=tariff, method="installment", installment_months=months, promo_code=promo
    )
    assert response.status_code == 201
    body = response.json()
    assert body["installment_months"] == months
    assert body["schedule"] == expected
    assert sum(body["schedule"]) == body["amount"]
    assert all(type(p) is int for p in body["schedule"])
    assert db.get_payment(body["id"]).schedule == expected


@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize("tariff", list(PRICES))
@pytest.mark.parametrize("promo", [None, "KVITTO10"])
def test_schedule_sum_equals_amount_everywhere(create_payment, tariff, promo, months):
    body = create_payment(
        tariff=tariff, method="installment", installment_months=months, promo_code=promo
    ).json()
    assert len(body["schedule"]) == months
    assert sum(body["schedule"]) == body["amount"]


def test_get_payment_returns_created_payment(client, create_payment):
    created = create_payment(method="installment", installment_months=6).json()
    response = client.get(f"/payments/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


@pytest.mark.parametrize("payment_id", ["00000000-0000-4000-8000-000000000000", "not-a-uuid", "1"])
def test_get_missing_payment_returns_404(client, payment_id):
    response = client.get(f"/payments/{payment_id}")
    assert response.status_code == 404


def test_unknown_promo_code_returns_422_and_creates_nothing(create_payment, db):
    response = create_payment(promo_code="WRONG")
    assert response.status_code == 422
    assert db.count_payments() == 0


def test_blank_promo_code_means_no_promo(create_payment):
    response = create_payment(promo_code="   ")
    assert response.status_code == 201
    assert response.json()["discount"] == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"method": "installment"},  # нет installment_months
        {"method": "installment", "installment_months": 5},
        {"method": "installment", "installment_months": 0},
        {"method": "card", "installment_months": 3},
        {"method": "sbp", "installment_months": 12},
        {"method": "bitcoin"},
        {"email": "not-an-email"},
        {"tariff_id": 9999},
        {"tariff_id": "abc"},
    ],
)
def test_invalid_requests_return_422(client, db, tariff_ids, overrides):
    body = {"tariff_id": tariff_ids["basic"], "email": "a@example.com", "method": "card"}
    body.update(overrides)
    response = client.post("/payments", json=body)
    assert response.status_code == 422
    assert db.count_payments() == 0


@pytest.mark.parametrize("missing", ["tariff_id", "email", "method"])
def test_missing_required_field_returns_422(client, tariff_ids, missing):
    body = {"tariff_id": tariff_ids["basic"], "email": "a@example.com", "method": "card"}
    del body[missing]
    assert client.post("/payments", json=body).status_code == 422
