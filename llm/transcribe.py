import asyncio
import io

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from config import settings
from llm.client import LLMUnavailableError

MODEL = "openai/whisper-1"
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)


async def transcribe_voice(audio_bytes: bytes, filename: str = "voice.ogg") -> str:
    """Распознаёт голосовое сообщение в текст через Whisper (OpenRouter — у него есть
    выделенный эндпоинт /audio/transcriptions, совместимый с openai SDK, поэтому не
    нужен отдельный ключ и отдельный релей, как для обычного chat-completions).

    Русский язык не указывается явно — Whisper определяет его сам и на практике
    справляется лучше без принудительной подсказки языка.
    """
    client = _client()
    audio_file = io.BytesIO(audio_bytes)
    audio_file.name = filename
    delay = BASE_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.audio.transcriptions.create(model=MODEL, file=audio_file)
            return response.text
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

    raise LLMUnavailableError(
        "Не получилось распознать голосовое сообщение — похоже, проблема с сетью. "
        "Попробуйте написать текстом или повторить чуть позже."
    ) from last_error
