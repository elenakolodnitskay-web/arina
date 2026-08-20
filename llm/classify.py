from dataclasses import dataclass

from db.models import Context
from llm.client import complete
from llm.json_parse import extract_json

CLASSIFY_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты классифицируешь сообщение пользователя личного ИИ-ассистента \
на один из двух контекстов: "work" (рабочее) или "personal" (личное).

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"context": "work" | "personal", "confidence": число от 0 до 1}"""


@dataclass
class ClassificationResult:
    context: Context
    confidence: float


async def classify_message(text: str) -> ClassificationResult:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=CLASSIFY_MODEL)
    data = extract_json(raw)
    return ClassificationResult(context=Context(data["context"]), confidence=float(data["confidence"]))
