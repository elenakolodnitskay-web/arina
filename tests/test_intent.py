from unittest.mock import AsyncMock

import pytest

from llm import intent


@pytest.mark.asyncio
async def test_detect_intent_task(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value='{"intent": "task"}'))

    result = await intent.detect_intent("напомни в 20:56 позвонить маме")

    assert result == intent.Intent.task


@pytest.mark.asyncio
async def test_detect_intent_chat(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value='{"intent": "chat"}'))

    result = await intent.detect_intent("сегодня был хороший день")

    assert result == intent.Intent.chat


@pytest.mark.asyncio
async def test_detect_intent_finance(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value='{"intent": "finance"}'))

    result = await intent.detect_intent("потратила 500 в Пятёрочке")

    assert result == intent.Intent.finance


@pytest.mark.asyncio
async def test_detect_intent_document(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value='{"intent": "document"}'))

    result = await intent.detect_intent("напиши письмо клиенту про перенос встречи")

    assert result == intent.Intent.document


@pytest.mark.asyncio
async def test_detect_intent_relay(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value='{"intent": "relay"}'))

    result = await intent.detect_intent("передай @ivan_petrov, что встреча переносится")

    assert result == intent.Intent.relay


@pytest.mark.asyncio
async def test_detect_intent_email(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value='{"intent": "email"}'))

    result = await intent.detect_intent("напиши на ivan@example.com, что оплата просрочена")

    assert result == intent.Intent.email


@pytest.mark.asyncio
async def test_detect_intent_parses_markdown_wrapped_json(monkeypatch):
    raw = '```json\n{"intent": "task"}\n```'
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value=raw))

    result = await intent.detect_intent("не забыть завтра оплатить счёт")

    assert result == intent.Intent.task


@pytest.mark.asyncio
async def test_detect_intent_raises_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(intent, "complete", AsyncMock(return_value="что-то без JSON"))

    with pytest.raises(ValueError):
        await intent.detect_intent("привет")
