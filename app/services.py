"""Прикладная логика: работа с БД и транзакциями."""

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domain import (
    TARIFFS,
    PaymentMethod,
    PaymentStatus,
    build_schedule,
    calculate_discount,
    can_transition,
    discount_percent,
)
from app.models import Payment, Tariff
from app.schemas import PaymentCreate


class TariffNotFoundError(Exception):
    pass


class PaymentNotFoundError(Exception):
    pass


class InvalidTransitionError(Exception):
    pass


def seed_tariffs(session_factory: sessionmaker[Session]) -> None:
    """Создаёт тарифы, которых ещё нет. Безопасно вызывать повторно."""
    with session_factory() as db:
        existing = set(db.scalars(select(Tariff.title)))
        for title, price in TARIFFS:
            if title not in existing:
                db.add(Tariff(title=title, price=price))
        try:
            db.commit()
        except IntegrityError:
            # Другой процесс успел создать тарифы одновременно с нами.
            db.rollback()


def _find_by_idempotency_key(db: Session, key: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.idempotency_key == key))


def create_payment(
    db: Session, data: PaymentCreate, idempotency_key: str | None
) -> tuple[Payment, bool]:
    """Создаёт платёж. Возвращает (платёж, создан_ли_новый).

    Если платёж с таким Idempotency-Key уже есть, возвращает его и False.
    """
    if idempotency_key is not None:
        existing = _find_by_idempotency_key(db, idempotency_key)
        if existing is not None:
            return existing, False

    tariff = db.get(Tariff, data.tariff_id)
    if tariff is None:
        raise TariffNotFoundError(data.tariff_id)

    discount = calculate_discount(tariff.price, discount_percent(data.promo_code))
    amount = tariff.price - discount

    schedule: list[int] | None = None
    if data.method == PaymentMethod.INSTALLMENT and data.installment_months is not None:
        schedule = build_schedule(amount, data.installment_months)

    payment = Payment(
        tariff_id=tariff.id,
        email=data.email,
        method=data.method.value,
        installment_months=data.installment_months,
        amount=amount,
        discount=discount,
        status=PaymentStatus.PENDING.value,
        schedule=schedule,
        promo_code=data.promo_code,
        idempotency_key=idempotency_key,
    )
    db.add(payment)
    try:
        db.commit()
    except IntegrityError:
        # Два одинаковых запроса прошли проверку выше одновременно: уникальный
        # индекс пропустил только один. Отдаём уже созданный платёж.
        db.rollback()
        if idempotency_key is not None:
            existing = _find_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing, False
        raise
    return payment, True


def get_payment(db: Session, payment_id: str) -> Payment | None:
    return db.get(Payment, payment_id)


def list_payments(
    db: Session,
    email: str | None,
    status: PaymentStatus | None,
    limit: int,
    offset: int,
) -> list[Payment]:
    stmt = select(Payment).order_by(Payment.created_at.desc(), Payment.id)
    if email:
        stmt = stmt.where(func.lower(Payment.email) == email.strip().lower())
    if status is not None:
        stmt = stmt.where(Payment.status == status.value)
    return list(db.scalars(stmt.limit(limit).offset(offset)))


def apply_bank_status(db: Session, payment_id: str, new_status: PaymentStatus) -> None:
    """Применяет статус от банка по таблице допустимых переходов."""
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise PaymentNotFoundError(payment_id)

    current = PaymentStatus(payment.status)
    if not can_transition(current, new_status):
        raise InvalidTransitionError(f"{current.value} -> {new_status.value}")

    # Атомарное условное обновление: если статус успели изменить параллельно,
    # строка не подойдёт под условие, и мы ничего не перезапишем.
    result = db.execute(
        update(Payment)
        .where(Payment.id == payment_id, Payment.status == current.value)
        .values(status=new_status.value)
    )
    if result.rowcount == 0:
        db.rollback()
        raise InvalidTransitionError(f"{current.value} -> {new_status.value}")
    db.commit()
