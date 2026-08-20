from db.models import Context
from llm.client import complete

REPLY_MODEL = "anthropic/claude-haiku-4.5"

CONTEXT_LABELS = {Context.work: "рабочее", Context.personal: "личное"}

SYSTEM_PROMPT_TEMPLATE = """Ты — Арина, личный ИИ-ассистент пользователя в Telegram. \
Помогаешь с рабочими и личными делами. Это сообщение отнесено к контексту: {context_label}.
{summary_block}
Ты умеешь ставить задачи и напоминания (разовые и повторяющиеся) по свободной \
формулировке — пользователю не нужна отдельная команда, достаточно попросить \
обычным текстом ("напомни...", "не забыть..."), и ты сама пришлёшь сообщение в \
нужное время через Telegram. Если пользователь спрашивает, умеешь ли ты напоминать \
или как это работает — отвечай, что да, умеешь, именно так и присылаешь напоминания.

Отвечай по-русски, коротко и по-человечески — как ассистент, который держит в уме \
контекст разговора, а не заполняет анкету. Не выдумывай факты, которых не было."""


async def generate_reply(text: str, context: Context, summary: str | None) -> str:
    summary_block = (
        f"\nКраткое summary предыдущих разговоров в этом контексте: {summary}" if summary else ""
    )
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        context_label=CONTEXT_LABELS[context], summary_block=summary_block
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]
    return await complete(messages, model=REPLY_MODEL)
