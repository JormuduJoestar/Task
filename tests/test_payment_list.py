"""GET /payments с фильтрами по email и status (бонус)."""

import pytest


@pytest.fixture
def three_payments(client, create_payment):
    first = create_payment(email="ann@example.com").json()["id"]
    second = create_payment(email="Ann@Example.com").json()["id"]
    third = create_payment(email="bob@example.com").json()["id"]
    client.post("/webhooks/bank", json={"payment_id": third, "status": "succeeded"})
    return first, second, third


def ids(response):
    return {p["id"] for p in response.json()}


def test_list_without_filters_returns_all(client, three_payments):
    response = client.get("/payments")
    assert response.status_code == 200
    assert ids(response) == set(three_payments)


def test_filter_by_email_is_case_insensitive(client, three_payments):
    first, second, _ = three_payments
    assert ids(client.get("/payments", params={"email": "ANN@example.com"})) == {first, second}


def test_filter_by_status(client, three_payments):
    first, second, third = three_payments
    assert ids(client.get("/payments", params={"status": "succeeded"})) == {third}
    assert ids(client.get("/payments", params={"status": "pending"})) == {first, second}
    assert ids(client.get("/payments", params={"status": "refunded"})) == set()


def test_filter_by_email_and_status(client, three_payments):
    _, _, third = three_payments
    response = client.get("/payments", params={"email": "bob@example.com", "status": "succeeded"})
    assert ids(response) == {third}


def test_unknown_status_filter_returns_422(client):
    assert client.get("/payments", params={"status": "paid"}).status_code == 422
