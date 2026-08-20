import httpx

from config import settings

MAX_API_BASE = "https://platform-api2.max.ru"


async def send_message(user_id: int, text: str) -> None:
    async with httpx.AsyncClient(base_url=MAX_API_BASE, timeout=30) as client:
        response = await client.post(
            "/messages",
            params={"user_id": user_id},
            headers={"Authorization": settings.max_bot_token},
            json={"text": text, "format": "markdown"},
        )
        response.raise_for_status()
