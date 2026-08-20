from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError

from llm import transcribe

_FAKE_REQUEST = httpx.Request("POST", "https://openrouter.ai/api/v1/audio/transcriptions")


def make_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    monkeypatch.setattr(transcribe.asyncio, "sleep", AsyncMock())


@pytest.mark.asyncio
async def test_transcribe_voice_returns_text_on_success(monkeypatch):
    fake_client = SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(create=AsyncMock(return_value=make_response("напомни завтра")))
        )
    )
    monkeypatch.setattr(transcribe, "_client", lambda: fake_client)

    result = await transcribe.transcribe_voice(b"fake audio bytes")

    assert result == "напомни завтра"


@pytest.mark.asyncio
async def test_transcribe_voice_retries_then_succeeds(monkeypatch):
    create = AsyncMock(
        side_effect=[APIConnectionError(request=_FAKE_REQUEST), make_response("ok после ретрая")]
    )
    fake_client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setattr(transcribe, "_client", lambda: fake_client)

    result = await transcribe.transcribe_voice(b"fake audio bytes")

    assert result == "ok после ретрая"
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_transcribe_voice_raises_russian_error_after_exhausting_retries(monkeypatch):
    create = AsyncMock(side_effect=APIConnectionError(request=_FAKE_REQUEST))
    fake_client = SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=create)))
    monkeypatch.setattr(transcribe, "_client", lambda: fake_client)

    with pytest.raises(transcribe.LLMUnavailableError, match="голосовое"):
        await transcribe.transcribe_voice(b"fake audio bytes")

    assert create.await_count == transcribe.MAX_RETRIES
