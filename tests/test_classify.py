from unittest.mock import AsyncMock

import pytest

from db.models import Context
from llm import classify


@pytest.mark.asyncio
async def test_classify_message_parses_clean_json(monkeypatch):
    monkeypatch.setattr(
        classify, "complete", AsyncMock(return_value='{"context": "work", "confidence": 0.92}')
    )

    result = await classify.classify_message("нужно отправить отчёт клиенту")

    assert result.context == Context.work
    assert result.confidence == pytest.approx(0.92)


@pytest.mark.asyncio
async def test_classify_message_parses_json_wrapped_in_markdown(monkeypatch):
    raw = '```json\n{"context": "personal", "confidence": 0.6}\n```'
    monkeypatch.setattr(classify, "complete", AsyncMock(return_value=raw))

    result = await classify.classify_message("купить подарок маме")

    assert result.context == Context.personal
    assert result.confidence == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_classify_message_raises_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(classify, "complete", AsyncMock(return_value="не знаю, простите"))

    with pytest.raises(ValueError):
        await classify.classify_message("что-то неоднозначное")
