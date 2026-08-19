import pytest

from db.models import User
from db.session import SessionLocal, engine

pytestmark = pytest.mark.skipif(
    engine.dialect.name != "postgresql",
    reason=(
        "Регрессия на переполнение int4 у telegram_id воспроизводится только на "
        "настоящем PostgreSQL (docker compose up) — на SQLite это ограничение типа "
        "не действует и баг не ловится"
    ),
)


def test_telegram_id_beyond_int32_range_is_accepted():
    # Реальный ID, который до фикса на BigInteger падал с
    # psycopg2.errors.NumericValueOutOfRange (int4 ограничен ±2^31-1 ≈ 2.147 млрд).
    large_telegram_id = 8866671232

    with SessionLocal() as session:
        user = User(telegram_id=large_telegram_id)
        session.add(user)
        session.commit()
        user_id = user.id

    try:
        with SessionLocal() as session:
            loaded = session.get(User, user_id)
            assert loaded.telegram_id == large_telegram_id
    finally:
        with SessionLocal() as session:
            session.query(User).filter_by(id=user_id).delete()
            session.commit()
