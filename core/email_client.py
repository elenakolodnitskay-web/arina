import httpx
from httpx import HTTPError

from config import settings

RESEND_API_URL = "https://api.resend.com/emails"


class EmailUnavailableError(Exception):
    """Понятная ошибка на русском при невозможности отправить email."""


async def send_email(to: str, subject: str, body: str) -> None:
    if not settings.resend_api_key or not settings.email_from_address:
        raise EmailUnavailableError(
            "Отправка email пока не настроена — сообщите об этом тому, кто "
            "администрирует Арину."
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
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
        except HTTPError as exc:
            raise EmailUnavailableError(
                "Не получилось отправить письмо — похоже, проблема с сетью. "
                "Попробуйте ещё раз чуть позже."
            ) from exc

    if response.status_code >= 400:
        raise EmailUnavailableError(
            f"Не получилось отправить письмо — сервис отправки вернул ошибку "
            f"({response.status_code})."
        )
