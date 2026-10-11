"""Идемпотентность POST /payments по заголовку Idempotency-Key."""

from app import services


def test_same_key_returns_same_payment_without_duplicate(create_payment, db):
    first = create_payment(idempotency_key="key-1")
    second = create_payment(idempotency_key="key-1")

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json() == first.json()
    assert db.count_payments() == 1


def test_different_keys_create_different_payments(create_payment, db):
    first = create_payment(idempotency_key="key-a")
    second = create_payment(idempotency_key="key-b")

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert db.count_payments() == 2


def test_without_key_every_request_creates_payment(create_payment, db):
    first = create_payment()
    second = create_payment()

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert db.count_payments() == 2


def test_blank_key_is_treated_as_missing(create_payment, db):
    first = create_payment(idempotency_key="   ")
    second = create_payment(idempotency_key="   ")

    assert first.status_code == second.status_code == 201
    assert db.count_payments() == 2


def test_key_longer_than_255_chars_returns_422(create_payment, db):
    response = create_payment(idempotency_key="k" * 256)
    assert response.status_code == 422
    assert db.count_payments() == 0


def test_replay_with_different_body_returns_original_payment(create_payment, db):
    # Поведение из задания: платёж с таким ключом уже есть — вернуть его же.
    first = create_payment(tariff="basic", idempotency_key="key-x")
    second = create_payment(tariff="premium", idempotency_key="key-x")

    assert second.status_code == 200
    assert second.json() == first.json()
    assert db.count_payments() == 1


def test_race_between_check_and_insert_returns_existing_payment(
    create_payment, db, monkeypatch
):
    """Имитация гонки: проверка по ключу «не видит» платёж, а вставку ловит UNIQUE."""
    first = create_payment(idempotency_key="key-race")
    assert first.status_code == 201

    real_find = services._find_by_idempotency_key
    calls = {"n": 0}

    def blind_first_call(session, key):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(session, key)

    monkeypatch.setattr(services, "_find_by_idempotency_key", blind_first_call)

    second = create_payment(idempotency_key="key-race")

    assert calls["n"] == 2  # сработала ветка IntegrityError
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert db.count_payments() == 1
