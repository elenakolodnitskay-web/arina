from unittest.mock import AsyncMock

import pytest

from core import finance


@pytest.mark.asyncio
async def test_parse_finance_message_expense(monkeypatch):
    raw = (
        '{"kind": "transaction", "amount": 500, "transaction_type": "expense", '
        '"category": "Пятёрочка"}'
    )
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value=raw))

    parsed = await finance.parse_finance_message("потратила 500 в Пятёрочке")

    assert parsed.kind == "transaction"
    assert parsed.amount == 500
    assert parsed.transaction_type == "expense"
    assert parsed.category == "Пятёрочка"


@pytest.mark.asyncio
async def test_parse_finance_message_income(monkeypatch):
    raw = '{"kind": "transaction", "amount": 80000, "transaction_type": "income", "category": "зарплата"}'
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value=raw))

    parsed = await finance.parse_finance_message("получил зарплату 80000")

    assert parsed.transaction_type == "income"
    assert parsed.amount == 80000


@pytest.mark.asyncio
async def test_parse_finance_message_balance(monkeypatch):
    raw = '{"kind": "balance", "amount": 3000, "transaction_type": null, "category": null}'
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value=raw))

    parsed = await finance.parse_finance_message("у меня на счёте осталось 3000")

    assert parsed.kind == "balance"
    assert parsed.amount == 3000
    assert parsed.transaction_type is None


@pytest.mark.asyncio
async def test_parse_finance_message_threshold(monkeypatch):
    raw = '{"kind": "threshold", "amount": 2000, "transaction_type": null, "category": null}'
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value=raw))

    parsed = await finance.parse_finance_message("предупреждай, если останется меньше 2000")

    assert parsed.kind == "threshold"
    assert parsed.amount == 2000


@pytest.mark.asyncio
async def test_parse_finance_message_returns_none_on_missing_amount(monkeypatch):
    raw = '{"kind": "transaction", "amount": null, "transaction_type": null, "category": null}'
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value=raw))

    parsed = await finance.parse_finance_message("что-то невнятное про деньги")

    assert parsed is None


@pytest.mark.asyncio
async def test_parse_finance_message_returns_none_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value="непонятно что"))

    parsed = await finance.parse_finance_message("что-то невнятное")

    assert parsed is None


@pytest.mark.asyncio
async def test_parse_finance_message_returns_none_on_non_numeric_amount(monkeypatch):
    raw = '{"kind": "transaction", "amount": "пятьсот", "transaction_type": "expense", "category": null}'
    monkeypatch.setattr(finance, "complete", AsyncMock(return_value=raw))

    parsed = await finance.parse_finance_message("потратила пятьсот рублей")

    assert parsed is None
