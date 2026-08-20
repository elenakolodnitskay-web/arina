from unittest.mock import AsyncMock

import pytest

from llm import documents


@pytest.mark.asyncio
async def test_generate_document_returns_parsed_docx(monkeypatch):
    raw = (
        '{"format": "docx", "title": "Письмо клиенту", '
        '"content": "Уважаемый Иван Иванович,\\n\\nПереносим встречу на пятницу."}'
    )
    fake_complete = AsyncMock(return_value=raw)
    monkeypatch.setattr(documents, "complete", fake_complete)

    result = await documents.generate_document("письмо клиенту с переносом встречи")

    assert result.format == "docx"
    assert result.title == "Письмо клиенту"
    assert "Уважаемый Иван Иванович" in result.content
    messages = fake_complete.await_args.args[0]
    assert messages[1]["content"] == "письмо клиенту с переносом встречи"
    assert fake_complete.await_args.kwargs["model"] == documents.DOCUMENTS_MODEL


@pytest.mark.asyncio
async def test_generate_document_returns_parsed_xlsx(monkeypatch):
    raw = (
        '{"format": "xlsx", "title": "Смета расходов", '
        '"content": "Статья|Сумма\\nАренда|30000\\nЗарплата|80000"}'
    )
    monkeypatch.setattr(documents, "complete", AsyncMock(return_value=raw))

    result = await documents.generate_document("смета расходов на аренду и зарплату")

    assert result.format == "xlsx"
    assert "Статья|Сумма" in result.content


@pytest.mark.asyncio
async def test_generate_document_raises_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(documents, "complete", AsyncMock(return_value="непонятно что"))

    with pytest.raises(ValueError):
        await documents.generate_document("что-то невнятное")
