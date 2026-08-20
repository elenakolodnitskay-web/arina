import json
import re
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from config import settings
from llm.client import complete

PARSE_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT_TEMPLATE = """Ты разбираешь свободную формулировку задачи или напоминания \
на структурированные поля. Текущее время (по местному времени пользователя, смещение \
от UTC уже учтено): {now}.

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{{"title": "короткая формулировка задачи в повелительном наклонении", \
"due_at": "ISO 8601 дата-время для разовой задачи или null — используй то же \
смещение от UTC, что и в текущем времени выше, НЕ переводи в UTC самостоятельно", \
"recurrence_rule": "cron-выражение из 5 полей (минута час день месяц день_недели) \
для повторяющейся задачи, по тому же местному времени, или null для разовой"}}

Примеры: "завтра в 18:00" -> due_at на завтра 18:00 по местному времени (то же \
смещение, что в текущем времени), recurrence_rule null. "каждый понедельник в 9" -> \
due_at null, recurrence_rule "0 9 * * 1" (9 утра по местному времени). "через час" \
-> due_at = текущее время + 1 час, recurrence_rule null.

Важно про неоднозначные числа вида "13.06" или "13.30": без явного слова "завтра", \
названия месяца или года — это почти всегда время (13:06 или 13:30 сегодня, если \
ещё не прошло, иначе завтра), а не дата (13 июня). Напоминания почти всегда ставят \
на ближайшее время, а не на год вперёд — если получившийся due_at более чем на \
месяц позже текущего времени, а в тексте не было явного указания на месяц/год, \
скорее всего это ошибка интерпретации: перечитай формулировку как время, а не дату."""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ParsedTask:
    title: str
    due_at: datetime | None
    recurrence_rule: str | None


def _extract_json(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))


async def parse_task(text: str) -> ParsedTask:
    now = datetime.now(ZoneInfo(settings.timezone)).isoformat()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_TEMPLATE.format(now=now)},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=PARSE_MODEL)
    data = _extract_json(raw)

    due_at = datetime.fromisoformat(data["due_at"]) if data.get("due_at") else None
    return ParsedTask(
        title=data["title"],
        due_at=due_at,
        recurrence_rule=data.get("recurrence_rule") or None,
    )
