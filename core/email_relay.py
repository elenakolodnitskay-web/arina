import json
import re
from dataclasses import dataclass

from llm.client import complete

PARSE_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты разбираешь просьбу отправить письмо-напоминание на email \
контакту, у которого нет Арины. В тексте должен быть явный email-адрес — извлеки \
его, короткую тему письма (3-6 слов) и сам текст письма на русском языке, \
написанный вежливо и по делу, от первого лица, без markdown-разметки. Если в \
тексте нет явного email-адреса — верни email: null.

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"email": "адрес@домен" | null, "subject": "короткая тема", "body": "текст письма"}"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ParsedEmail:
    email: str | None
    subject: str
    body: str


def _extract_json(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))


async def parse_email_message(text: str) -> ParsedEmail:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=PARSE_MODEL)
    data = _extract_json(raw)

    email = data.get("email")
    if email and not _EMAIL_RE.match(email):
        email = None

    return ParsedEmail(email=email, subject=data["subject"], body=data["body"])
