from dataclasses import dataclass

from llm.client import complete
from llm.json_parse import extract_json

# Для документов/писем — более сильная модель, чем для классификации/разбора задач:
# здесь важно качество текста (репутационный риск ложится на пользователя после
# подтверждения, см. спецификацию), а не скорость/цена.
DOCUMENTS_MODEL = "anthropic/claude-sonnet-4.5"

SYSTEM_PROMPT = """Ты помогаешь пользователю подготовить готовый документ по словесному \
описанию. Сама определи подходящий формат файла, если пользователь явно не указал \
другой: "docx" для писем, договоров, заявлений и вообще любого связного текста; \
"xlsx" для таблиц, смет, списков расходов/данных по строкам и столбцам; "pdf" для \
документов, которые обычно не редактируют после подготовки (счета, официальные \
бланки). Если сомневаешься между docx и pdf — выбирай docx.

Ответь строго JSON без пояснений и без markdown-разметки, в формате:
{"format": "docx" | "xlsx" | "pdf", \
"title": "короткое название документа (3-6 слов, будет использовано как имя файла)", \
"content": "готовый текст документа на русском языке для docx/pdf — абзацы \
разделены двойным переносом строки \\n\\n, без markdown-разметки и без \
мета-комментариев о том, что ты сделал; ИЛИ для xlsx — таблица, где каждая строка \
таблицы на отдельной строке текста, а ячейки внутри строки разделены символом |, \
первая строка — заголовки столбцов"}"""

@dataclass
class ParsedDocument:
    format: str
    title: str
    content: str


async def generate_document(description: str) -> ParsedDocument:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": description},
    ]
    raw = await complete(messages, model=DOCUMENTS_MODEL)
    data = extract_json(raw)
    return ParsedDocument(
        format=data["format"],
        title=data["title"],
        content=data["content"],
    )
