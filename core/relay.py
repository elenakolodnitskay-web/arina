import json
import re
from dataclasses import dataclass

from llm.client import complete

PARSE_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты разбираешь просьбу переслать сообщение другому пользователю \
Telegram по его @username, упомянутому в тексте. Извлеки username получателя (без \
символа @) и сам текст, который нужно передать — только содержание сообщения, без \
вводных слов вроде "передай", "напиши ему", "скажи, что". Если в тексте нет явного \
@username — верни username: null.

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"username": "имя_без_собаки" | null, "message": "текст для пересылки"}"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ParsedRelay:
    username: str | None
    message: str


def _extract_json(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))


async def parse_relay_message(text: str) -> ParsedRelay:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=PARSE_MODEL)
    data = _extract_json(raw)
    return ParsedRelay(username=data.get("username"), message=data["message"])
