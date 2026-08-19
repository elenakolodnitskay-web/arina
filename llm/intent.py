import json
import re
from enum import Enum

from llm.client import complete

INTENT_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты определяешь намерение пользователя личного ИИ-ассистента в \
свободном сообщении: хочет ли он поставить задачу/напоминание ("task") или просто \
делится мыслью, договорённостью, вопросом — общается в свободной форме ("chat").

Признаки task: явная или подразумеваемая просьба напомнить, не забыть, сделать \
что-то к сроку или регулярно ("напомни...", "не забыть...", "каждый день...", \
"завтра нужно...", "через час..."). Если срока или повторения нет — это chat, даже \
если сообщение про дела.

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"intent": "task" | "chat"}"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


class Intent(str, Enum):
    task = "task"
    chat = "chat"


def _extract_json(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))


async def detect_intent(text: str) -> Intent:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=INTENT_MODEL)
    data = _extract_json(raw)
    return Intent(data["intent"])
