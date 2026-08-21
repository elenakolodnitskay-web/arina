import asyncio

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from config import settings
from llm.client import LLMUnavailableError

# openai/text-embedding-3-small через OpenRouter — тот же base_url/ключ/релей, что
# для чата и распознавания голоса (проверено живьём: /embeddings проходит через
# тот же релей на Render.com и напрямую с прод-сервера Beget, никакой новый
# провайдер/канал не понадобился). 1536 измерений (см. db/models.py::EMBEDDING_DIM
# — смена модели потребует новой миграции).
MODEL = "openai/text-embedding-3-small"
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)


async def get_embedding(text: str) -> list[float]:
    client = _client()
    delay = BASE_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.embeddings.create(model=MODEL, input=text)
            return response.data[0].embedding
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

    raise LLMUnavailableError(
        "Не получилось связаться с сервисом эмбеддингов — похоже, проблема с сетью."
    ) from last_error


async def get_embedding_or_none(text: str) -> list[float] | None:
    """Эмбеддинг — дополнение к памяти (Фаза 27), не критичный путь: если сервис
    недоступен, вызывающий код должен продолжить работу без эмбеддинга (просто не
    участвует в семантическом поиске), а не падать целиком — в отличие от
    detect_intent/classify_message, без которых обработка сообщения невозможна.
    """
    try:
        return await get_embedding(text)
    except LLMUnavailableError:
        return None
