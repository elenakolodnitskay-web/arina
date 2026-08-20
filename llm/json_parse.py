import json
import re

# Общий разбор структурированного JSON-ответа модели — используется во всех местах,
# где LLM просят вернуть строгий JSON (intent.py, classify.py, documents.py,
# core/tasks.py, core/finance.py, core/relay.py, core/email_relay.py), но модель
# иногда оборачивает ответ в пояснения или markdown — этот regex вытаскивает первый
# блок в фигурных скобках, не полагаясь на то, что весь ответ — валидный JSON.
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(raw: str) -> dict:
    match = JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))
