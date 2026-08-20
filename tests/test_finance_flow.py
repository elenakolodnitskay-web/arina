from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import finance_flow
from core.finance import ParsedFinance
from db.models import Base, Transaction, TransactionType, User


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(finance_flow, "SessionLocal", factory)
    yield factory
    engine.dispose()


def make_user(db_session_factory, **kwargs) -> int:
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True, **kwargs)
        session.add(user)
        session.commit()
        return user.id


@pytest.mark.parametrize(
    "amount, expected",
    [
        (500, "500"),
        (500.0, "500"),
        (199.99, "199.99"),
        (199.90, "199.9"),
        (0.5, "0.5"),
    ],
)
def test_format_amount_shows_exact_value_without_padding(amount, expected):
    assert finance_flow._format_amount(amount) == expected


@pytest.mark.asyncio
async def test_record_finance_message_does_not_round_fractional_amount(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(
            return_value=ParsedFinance(
                kind="transaction", amount=199.99, transaction_type="expense", category="аптека"
            )
        ),
    )

    reply = await finance_flow.record_finance_message(user_id, "потратила 199.99 в аптеке")

    assert "199.99" in reply
    assert "200" not in reply


@pytest.mark.asyncio
async def test_record_finance_message_saves_expense(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(
            return_value=ParsedFinance(
                kind="transaction", amount=500, transaction_type="expense", category="Пятёрочка"
            )
        ),
    )

    reply = await finance_flow.record_finance_message(user_id, "потратила 500 в Пятёрочке")

    assert "500" in reply
    assert "Пятёрочка" in reply
    with db_session_factory() as session:
        transaction = session.query(Transaction).one()
        assert transaction.amount == 500
        assert transaction.transaction_type == TransactionType.expense
        assert transaction.description == "Пятёрочка"


@pytest.mark.asyncio
async def test_record_finance_message_saves_income(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(
            return_value=ParsedFinance(kind="transaction", amount=80000, transaction_type="income", category=None)
        ),
    )

    reply = await finance_flow.record_finance_message(user_id, "получил зарплату 80000")

    assert "поступление" in reply
    with db_session_factory() as session:
        transaction = session.query(Transaction).one()
        assert transaction.transaction_type == TransactionType.income


@pytest.mark.asyncio
async def test_record_finance_message_updates_balance(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(return_value=ParsedFinance(kind="balance", amount=3000, transaction_type=None, category=None)),
    )

    reply = await finance_flow.record_finance_message(user_id, "у меня на счёте осталось 3000")

    assert "3000" in reply
    assert "⚠️" not in reply
    with db_session_factory() as session:
        user = session.get(User, user_id)
        assert user.balance == 3000


@pytest.mark.asyncio
async def test_record_finance_message_warns_on_low_balance(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory, low_balance_threshold=2000)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(return_value=ParsedFinance(kind="balance", amount=1500, transaction_type=None, category=None)),
    )

    reply = await finance_flow.record_finance_message(user_id, "баланс 1500")

    assert "⚠️" in reply
    assert "2000" in reply


@pytest.mark.asyncio
async def test_record_finance_message_no_warning_above_threshold(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory, low_balance_threshold=2000)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(return_value=ParsedFinance(kind="balance", amount=5000, transaction_type=None, category=None)),
    )

    reply = await finance_flow.record_finance_message(user_id, "баланс 5000")

    assert "⚠️" not in reply


@pytest.mark.asyncio
async def test_record_finance_message_sets_threshold(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory)
    monkeypatch.setattr(
        finance_flow,
        "parse_finance_message",
        AsyncMock(return_value=ParsedFinance(kind="threshold", amount=2000, transaction_type=None, category=None)),
    )

    reply = await finance_flow.record_finance_message(user_id, "предупреждай, если останется меньше 2000")

    assert "2000" in reply
    with db_session_factory() as session:
        user = session.get(User, user_id)
        assert user.low_balance_threshold == 2000


@pytest.mark.asyncio
async def test_record_finance_message_returns_none_when_unparseable(db_session_factory, monkeypatch):
    user_id = make_user(db_session_factory)
    monkeypatch.setattr(finance_flow, "parse_finance_message", AsyncMock(return_value=None))

    reply = await finance_flow.record_finance_message(user_id, "что-то невнятное")

    assert reply is None
    with db_session_factory() as session:
        assert session.query(Transaction).count() == 0
