from unittest.mock import AsyncMock

import pytest

from core import email_relay


@pytest.mark.asyncio
async def test_parse_email_message_extracts_address_subject_body(monkeypatch):
    raw = (
        '{"email": "ivan@example.com", "subject": "Оплата просрочена", '
        '"body": "Добрый день! Напоминаем, что оплата просрочена."}'
    )
    monkeypatch.setattr(email_relay, "complete", AsyncMock(return_value=raw))

    parsed = await email_relay.parse_email_message("напиши на ivan@example.com, что оплата просрочена")

    assert parsed.email == "ivan@example.com"
    assert parsed.subject == "Оплата просрочена"
    assert "оплата просрочена" in parsed.body.lower()


@pytest.mark.asyncio
async def test_parse_email_message_returns_none_without_address(monkeypatch):
    raw = '{"email": null, "subject": "Оплата", "body": "Напомни Ивану про оплату"}'
    monkeypatch.setattr(email_relay, "complete", AsyncMock(return_value=raw))

    parsed = await email_relay.parse_email_message("напомни Ивану про оплату")

    assert parsed.email is None


@pytest.mark.asyncio
async def test_parse_email_message_rejects_malformed_address(monkeypatch):
    raw = '{"email": "не email адрес", "subject": "Тема", "body": "Текст"}'
    monkeypatch.setattr(email_relay, "complete", AsyncMock(return_value=raw))

    parsed = await email_relay.parse_email_message("что-то невнятное")

    assert parsed.email is None


@pytest.mark.asyncio
async def test_parse_email_message_raises_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(email_relay, "complete", AsyncMock(return_value="непонятно что"))

    with pytest.raises(ValueError):
        await email_relay.parse_email_message("что-то невнятное")
