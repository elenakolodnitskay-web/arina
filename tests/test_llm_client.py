from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from llm import client

_FAKE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def make_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(client.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_complete_returns_content_on_success(monkeypatch):
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=AsyncMock(return_value=make_response("привет")))
        )
    )
    monkeypatch.setattr(client, "_client", lambda: fake_client)

    result = await client.complete([{"role": "user", "content": "hi"}])

    assert result == "привет"


@pytest.mark.asyncio
async def test_complete_retries_then_succeeds(monkeypatch):
    create = AsyncMock(
        side_effect=[APIConnectionError(request=_FAKE_REQUEST), make_response("ok после ретрая")]
    )
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "_client", lambda: fake_client)

    result = await client.complete([{"role": "user", "content": "hi"}])

    assert result == "ok после ретрая"
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_complete_raises_russian_error_after_exhausting_retries(monkeypatch):
    create = AsyncMock(side_effect=APIConnectionError(request=_FAKE_REQUEST))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "_client", lambda: fake_client)

    with pytest.raises(client.LLMUnavailableError, match="ИИ-моделью"):
        await client.complete([{"role": "user", "content": "hi"}])

    assert create.await_count == client.MAX_RETRIES
