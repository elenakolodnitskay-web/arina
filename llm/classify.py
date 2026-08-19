import json
import re
from dataclasses import dataclass

from db.models import Context
from llm.client import complete

CLASSIFY_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты классифицируешь сообщение пользователя личного ИИ-ассистента \
на один из двух контекстов: "work" (рабочее) или "personal" (личное).

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"context": "work" | "personal", "confidence": число от 0 до 1}"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ClassificationResult:
    context: Context
    confidence: float


def _extract_json(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))


async def classify_message(text: str) -> ClassificationResult:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=CLASSIFY_MODEL)
    data = _extract_json(raw)
    return ClassificationResult(context=Context(data["context"]), confidence=float(data["confidence"]))
