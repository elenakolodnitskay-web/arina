from unittest.mock import AsyncMock

import pytest

from llm import documents


@pytest.mark.asyncio
async def test_generate_document_returns_draft_text(monkeypatch):
    fake_complete = AsyncMock(return_value="Уважаемый Иван Иванович, ...")
    monkeypatch.setattr(documents, "complete", fake_complete)

    result = await documents.generate_document("письмо клиенту с переносом встречи")

    assert result == "Уважаемый Иван Иванович, ..."
    messages = fake_complete.await_args.args[0]
    assert messages[1]["content"] == "письмо клиенту с переносом встречи"
    assert fake_complete.await_args.kwargs["model"] == documents.DOCUMENTS_MODEL
