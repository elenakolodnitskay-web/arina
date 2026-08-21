from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from llm import embeddings

_FAKE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/embeddings")


def make_response(vector: list[float]) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(embedding=vector)])


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(embeddings.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_get_embedding_returns_vector_on_success(monkeypatch):
    fake_vector = [0.1, 0.2, 0.3]
    create = AsyncMock(return_value=make_response(fake_vector))
    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr(embeddings, "_client", lambda: fake_client)

    result = await embeddings.get_embedding("тестовый текст")

    assert result == fake_vector
    assert create.await_args.kwargs["model"] == embeddings.MODEL
    assert create.await_args.kwargs["input"] == "тестовый текст"


@pytest.mark.asyncio
async def test_get_embedding_retries_then_succeeds(monkeypatch):
    create = AsyncMock(side_effect=[APIConnectionError(request=_FAKE_REQUEST), make_response([0.5])])
    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr(embeddings, "_client", lambda: fake_client)

    result = await embeddings.get_embedding("текст")

    assert result == [0.5]
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_get_embedding_raises_russian_error_after_exhausting_retries(monkeypatch):
    create = AsyncMock(side_effect=APIConnectionError(request=_FAKE_REQUEST))
    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
    monkeypatch.setattr(embeddings, "_client", lambda: fake_client)

    with pytest.raises(embeddings.LLMUnavailableError, match="эмбеддингов"):
        await embeddings.get_embedding("текст")

    assert create.await_count == embeddings.MAX_RETRIES


@pytest.mark.asyncio
async def test_get_embedding_or_none_returns_vector_on_success(monkeypatch):
    fake_vector = [0.1, 0.2]
    monkeypatch.setattr(embeddings, "get_embedding", AsyncMock(return_value=fake_vector))

    result = await embeddings.get_embedding_or_none("текст")

    assert result == fake_vector


@pytest.mark.asyncio
async def test_get_embedding_or_none_returns_none_on_failure(monkeypatch):
    monkeypatch.setattr(
        embeddings, "get_embedding", AsyncMock(side_effect=embeddings.LLMUnavailableError("сеть недоступна"))
    )

    result = await embeddings.get_embedding_or_none("текст")

    assert result is None
