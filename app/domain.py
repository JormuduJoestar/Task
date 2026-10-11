"""Бизнес-правила платежей.

Модуль не зависит ни от FastAPI, ни от базы данных: только константы и чистые функции.
Все суммы — целые числа в копейках. Никакого float: только int, //, % и divmod.
Чтобы изменить правило (новый промокод, срок рассрочки, переход статуса),
достаточно поправить соответствующую константу ниже.
"""

from enum import StrEnum


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(StrEnum):
    CARD = "card"
    SBP = "sbp"
    INSTALLMENT = "installment"


# Тарифы, создаваемые при старте: (название, цена в копейках).
TARIFFS: tuple[tuple[str, int], ...] = (
    ("basic", 990000),  # 9 900 ₽
    ("standard", 1990000),  # 19 900 ₽
    ("premium", 2990000),  # 29 900 ₽
)

# Промокоды: код (в верхнем регистре) -> скидка в процентах от цены тарифа.
PROMO_CODES: dict[str, int] = {"KVITTO10": 10}

# Допустимые сроки рассрочки в месяцах.
INSTALLMENT_MONTHS: tuple[int, ...] = (3, 6, 12)

# Допустимые переходы статусов. Всё, чего нет в таблице, запрещено
# (в том числе «переход» в тот же самый статус).
ALLOWED_TRANSITIONS: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.PENDING: frozenset({PaymentStatus.SUCCEEDED, PaymentStatus.FAILED}),
    PaymentStatus.SUCCEEDED: frozenset({PaymentStatus.REFUNDED}),
    PaymentStatus.FAILED: frozenset(),
    PaymentStatus.REFUNDED: frozenset(),
}


class UnknownPromoCodeError(ValueError):
    """Промокод не найден."""


def normalize_promo_code(code: str | None) -> str | None:
    """Убирает пробелы по краям и приводит к верхнему регистру.

    None и пустая строка означают «промокод не передан».
    """
    if code is None:
        return None
    normalized = code.strip().upper()
    return normalized or None


def discount_percent(code: str | None) -> int:
    """Скидка в процентах для промокода (0, если промокода нет).

    Неизвестный код — UnknownPromoCodeError.
    """
    normalized = normalize_promo_code(code)
    if normalized is None:
        return 0
    try:
        return PROMO_CODES[normalized]
    except KeyError:
        raise UnknownPromoCodeError(f"Unknown promo code: {code!r}") from None


def calculate_discount(price: int, percent: int) -> int:
    """Скидка в копейках. Целочисленное деление: дробные копейки отбрасываются.

    Сумма к оплате считается как price - discount, поэтому
    amount + discount == price выполняется всегда.
    """
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return price * percent // 100


def build_schedule(amount: int, months: int) -> list[int]:
    """График рассрочки: amount делится на months платежей в копейках.

    Сумма платежей ровно равна amount, лишние копейки уходят в первые платежи:
    1990000 на 3 месяца -> [663334, 663333, 663333].
    """
    if months <= 0:
        raise ValueError("months must be positive")
    base, remainder = divmod(amount, months)
    return [base + 1] * remainder + [base] * (months - remainder)


def can_transition(current: PaymentStatus, new: PaymentStatus) -> bool:
    """Разрешён ли переход current -> new."""
    return new in ALLOWED_TRANSITIONS[current]
