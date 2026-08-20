from dataclasses import dataclass

from llm.client import complete
from llm.json_parse import extract_json

PARSE_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты разбираешь просьбу переслать сообщение другому пользователю \
Telegram по его @username, упомянутому в тексте. Извлеки username получателя (без \
символа @) и сам текст, который нужно передать — только содержание сообщения, без \
вводных слов вроде "передай", "напиши ему", "скажи, что". Если в тексте нет явного \
@username — верни username: null.

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"username": "имя_без_собаки" | null, "message": "текст для пересылки"}"""

@dataclass
class ParsedRelay:
    username: str | None
    message: str


async def parse_relay_message(text: str) -> ParsedRelay:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=PARSE_MODEL)
    data = extract_json(raw)
    return ParsedRelay(username=data.get("username"), message=data["message"])
