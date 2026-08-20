import json
import re
from dataclasses import dataclass

from llm.client import complete

PARSE_MODEL = "anthropic/claude-haiku-4.5"

SYSTEM_PROMPT = """Ты разбираешь сообщение пользователя личного финансового ассистента \
на структурированные поля. Пользователь пишет одно из трёх:

1. О трате или поступлении денег: "потратила 500 в Пятёрочке", "получил зарплату \
80000", "заплатил 3000 за коммуналку".
2. Текущий остаток на счёте/балансе (не трату, а именно итоговую сумму, которая \
сейчас есть): "у меня на счёте осталось 3000", "баланс 5000", "на карте 12000".
3. Порог для предупреждения о низком балансе — просьба следить и предупреждать, \
если баланс станет меньше названной суммы: "предупреждай, если останется меньше \
2000", "скажи, если баланс упадёт ниже 1000".

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"kind": "transaction" | "balance" | "threshold", \
"amount": число (сумма операции, ИЛИ итоговый баланс, ИЛИ порог — всегда положительное), \
"transaction_type": "expense" | "income" | null (заполняй только для kind="transaction"), \
"category": "короткое название категории/места/статьи (магазин, коммуналка, зарплата и т.п.)" \
| null (заполняй только для kind="transaction")}"""

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class ParsedFinance:
    kind: str
    amount: float
    transaction_type: str | None
    category: str | None


def _extract_json(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if match is None:
        raise ValueError(f"Не удалось найти JSON в ответе модели: {raw!r}")
    return json.loads(match.group(0))


async def parse_finance_message(text: str) -> ParsedFinance | None:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]
    raw = await complete(messages, model=PARSE_MODEL)
    data = _extract_json(raw)

    if data.get("kind") not in ("transaction", "balance", "threshold") or data.get("amount") is None:
        return None

    return ParsedFinance(
        kind=data["kind"],
        amount=float(data["amount"]),
        transaction_type=data.get("transaction_type"),
        category=data.get("category"),
    )
