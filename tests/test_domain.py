"""Тесты чистой бизнес-логики (без HTTP и без БД)."""

import itertools
from fractions import Fraction

import pytest

from app.domain import (
    PROMO_CODES,
    TARIFFS,
    PaymentStatus,
    UnknownPromoCodeError,
    build_schedule,
    calculate_discount,
    can_transition,
    discount_percent,
    normalize_promo_code,
)


def test_tariff_prices_are_integer_kopecks():
    assert dict(TARIFFS) == {"basic": 990000, "standard": 1990000, "premium": 2990000}
    assert all(type(price) is int for _, price in TARIFFS)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("KVITTO10", "KVITTO10"),
        ("kvitto10", "KVITTO10"),
        ("  KvItTo10 ", "KVITTO10"),
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_promo_code(raw, expected):
    assert normalize_promo_code(raw) == expected


def test_discount_percent_known_unknown_and_missing():
    assert discount_percent("kvitto10") == PROMO_CODES["KVITTO10"] == 10
    assert discount_percent(None) == 0
    with pytest.raises(UnknownPromoCodeError):
        discount_percent("NOPE")


@pytest.mark.parametrize(
    ("price", "discount"),
    [(990000, 99000), (1990000, 199000), (2990000, 299000)],
)
def test_discount_for_tariffs(price, discount):
    assert calculate_discount(price, 10) == discount
    assert calculate_discount(price, 0) == 0


def test_discount_matches_exact_arithmetic_for_all_percents():
    # Точный эталон через Fraction: float здесь ошибся бы, например 100 * 0.29 = 28.999...
    for price in range(1, 400):
        for percent in range(0, 101):
            expected = int(Fraction(price * percent, 100))  # целая часть, дробь отброшена
            result = calculate_discount(price, percent)
            assert result == expected
            assert type(result) is int


def test_discount_rounds_down_and_keeps_sum_exact():
    # Соглашение: дробные копейки скидки отбрасываются, остаток остаётся в сумме к оплате.
    price = 1999
    discount = calculate_discount(price, 10)
    assert discount == 199
    assert price - discount == 1800
    assert (price - discount) + discount == price


@pytest.mark.parametrize(
    ("amount", "months", "expected"),
    [
        (1990000, 3, [663334, 663333, 663333]),  # пример из задания
        (1990000, 6, [331667] * 4 + [331666] * 2),
        (1990000, 12, [165834] * 4 + [165833] * 8),
        (2990000, 3, [996667, 996667, 996666]),
        (2990000, 6, [498334] * 2 + [498333] * 4),
        (2990000, 12, [249167] * 8 + [249166] * 4),
        (990000, 3, [330000] * 3),
        (1791000, 12, [149250] * 12),
    ],
)
def test_build_schedule_exact_values(amount, months, expected):
    schedule = build_schedule(amount, months)
    assert schedule == expected
    assert sum(schedule) == amount


@pytest.mark.parametrize("months", [3, 6, 12, 7])
def test_build_schedule_properties(months):
    for amount in list(range(1, 200)) + [990000, 1990000, 2990000, 1791000, 2691000, 891000]:
        schedule = build_schedule(amount, months)
        assert len(schedule) == months
        assert sum(schedule) == amount
        assert all(type(p) is int for p in schedule)
        assert max(schedule) - min(schedule) <= 1
        assert schedule == sorted(schedule, reverse=True)  # лишние копейки — в первых платежах


# Эталон допустимых переходов записан независимо от таблицы в приложении.
ALLOWED = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}


@pytest.mark.parametrize(
    ("current", "new"), list(itertools.product(PaymentStatus, PaymentStatus))
)
def test_can_transition_matrix(current, new):
    assert can_transition(current, new) is ((current.value, new.value) in ALLOWED)
