import asyncio

import httpx
from httpx import HTTPError

from config import settings

RESEND_API_URL = "https://api.resend.com/emails"
MAX_RETRIES = 3
BASE_DELAY_SECONDS = 1.0


class EmailUnavailableError(Exception):
    """Понятная ошибка на русском при невозможности отправить email."""


async def send_email(to: str, subject: str, body: str) -> None:
    if not settings.resend_api_key or not settings.email_from_address:
        raise EmailUnavailableError(
            "Отправка email пока не настроена — сообщите об этом тому, кто "
            "администрирует Арину."
        )

    delay = BASE_DELAY_SECONDS
    last_error: Exception | None = None
    response = None

    # Ретраи только на сетевые сбои (тот же паттерн, что llm/client.py) — ошибка
    # статуса от Resend (4xx/5xx) обычно не временная, повторять её нет смысла.
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    RESEND_API_URL,
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": settings.email_from_address,
                        "to": [to],
                        "subject": subject,
                        "text": body,
                    },
                )
            break
        except HTTPError as exc:
            last_error = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(delay)
                delay *= 2

    if response is None:
        raise EmailUnavailableError(
            "Не получилось отправить письмо — похоже, проблема с сетью. "
            "Попробуйте ещё раз чуть позже."
        ) from last_error

    if response.status_code >= 400:
        raise EmailUnavailableError(
            f"Не получилось отправить письмо — сервис отправки вернул ошибку "
            f"({response.status_code})."
        )
