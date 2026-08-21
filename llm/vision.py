import asyncio
import base64

from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from config import settings
from llm.client import LLMUnavailableError

# Распознавание текста с фото (Фаза 30) — проверено живьём: chat.completions с
# image_url (data URI, base64) на той же модели anthropic/claude-haiku-4.5, что уже
# используется для чата/классификации — отдельный OCR-провайдер не понадобился.
MODEL = "anthropic/claude-haiku-4.5"
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0

SYSTEM_PROMPT = (
    "Перепиши ВЕСЬ видимый текст с изображения дословно, символ в символ, без "
    "пояснений, комментариев и оценок от себя — только сам текст. Сохраняй разбивку "
    "на строки/абзацы, если она есть. Если на изображении нет текста — ответь пустой "
    "строкой, не пиши описание картинки."
)


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(base_url=settings.openrouter_base_url, api_key=settings.openrouter_api_key)


def _guess_mime_type(image_bytes: bytes) -> str:
    if image_bytes[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image_bytes[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def extract_text_from_image(image_bytes: bytes) -> str:
    client = _client()
    mime_type = _guess_mime_type(image_bytes)
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
    delay = BASE_DELAY_SECONDS
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [{"type": "image_url", "image_url": {"url": data_url}}],
                    },
                ],
            )
            return response.choices[0].message.content or ""
        except (APIConnectionError, APITimeoutError) as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

    raise LLMUnavailableError(
        "Не получилось распознать текст на фото — похоже, проблема с сетью. "
        "Попробуйте ещё раз через пару минут."
    ) from last_error
