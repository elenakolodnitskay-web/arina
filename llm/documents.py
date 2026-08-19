from llm.client import complete

# Для документов/писем — более сильная модель, чем для классификации/разбора задач:
# здесь важно качество текста (репутационный риск ложится на пользователя после
# подтверждения, см. спецификацию), а не скорость/цена.
DOCUMENTS_MODEL = "anthropic/claude-sonnet-4.5"

SYSTEM_PROMPT = """Ты помогаешь пользователю написать письмо или документ с нуля по \
словесному описанию. Напиши готовый черновик текста на русском языке — без \
пояснений, без markdown-разметки, без мета-комментариев о том, что ты сделал. \
Только сам текст письма/документа, готовый к тому, чтобы пользователь его \
отредактировал и использовал."""


async def generate_document(description: str) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": description},
    ]
    return await complete(messages, model=DOCUMENTS_MODEL)
