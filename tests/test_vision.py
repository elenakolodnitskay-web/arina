from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from llm import vision

_FAKE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 10
_JPEG_MAGIC = b"\xff\xd8\xff" + b"\x00" * 10


def make_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(vision.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_extract_text_from_image_returns_content(monkeypatch):
    create = AsyncMock(return_value=make_response("Привет, Ваня!"))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vision, "_client", lambda: fake_client)

    result = await vision.extract_text_from_image(_PNG_MAGIC)

    assert result == "Привет, Ваня!"


@pytest.mark.asyncio
async def test_extract_text_from_image_passes_data_url_with_correct_mime(monkeypatch):
    create = AsyncMock(return_value=make_response(""))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vision, "_client", lambda: fake_client)

    await vision.extract_text_from_image(_JPEG_MAGIC)

    content = create.await_args.kwargs["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "дословно" in create.await_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_extract_text_from_image_returns_empty_string_when_no_text(monkeypatch):
    create = AsyncMock(return_value=make_response(""))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vision, "_client", lambda: fake_client)

    result = await vision.extract_text_from_image(_PNG_MAGIC)

    assert result == ""


@pytest.mark.asyncio
async def test_extract_text_from_image_retries_then_succeeds(monkeypatch):
    create = AsyncMock(side_effect=[APIConnectionError(request=_FAKE_REQUEST), make_response("текст")])
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vision, "_client", lambda: fake_client)

    result = await vision.extract_text_from_image(_PNG_MAGIC)

    assert result == "текст"
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_extract_text_from_image_raises_russian_error_after_exhausting_retries(monkeypatch):
    create = AsyncMock(side_effect=APIConnectionError(request=_FAKE_REQUEST))
    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(vision, "_client", lambda: fake_client)

    with pytest.raises(vision.LLMUnavailableError, match="проблема с сетью"):
        await vision.extract_text_from_image(_PNG_MAGIC)

    assert create.await_count == vision.MAX_RETRIES
