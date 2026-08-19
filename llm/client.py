import asyncio

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from config import settings

DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0


class LLMUnavailableError(Exception):
    """Понятная ошибка на русском при исчерпании попыток обращения к LLM."""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)


async def complete(messages: list[dict], model: str = DEFAULT_MODEL) -> str:
    client = _client()
    delay = BASE_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(model=model, messages=messages)
            return response.choices[0].message.content
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

    raise LLMUnavailableError(
        "Не получилось связаться с ИИ-моделью — похоже, проблема с сетью. "
        "Попробуйте написать ещё раз через пару минут."
    ) from last_error
