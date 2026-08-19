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
