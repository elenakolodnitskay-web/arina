from db.models import Context, DialogSummary, Note
from db.session import SessionLocal
from llm.client import complete

RESUMMARIZE_MODEL = "anthropic/claude-haiku-4.5"

# Временное значение — окно/частота пересуммаризации не зафиксированы в
# спецификации («открытый вопрос»), уточняется по факту ручного тестирования.
MESSAGE_THRESHOLD = 8

SYSTEM_PROMPT = """Ты обновляешь краткое скользящее summary диалога с пользователем \
личного ИИ-ассистента. У тебя есть предыдущее summary (может быть пустым) и новые \
сообщения пользователя с момента последнего обновления. Составь новое краткое \
summary (3-5 предложений), сохраняющее важные факты, договорённости и детали, \
которые могут понадобиться в следующих разговорах. Не выдумывай факты, которых не \
было. Ответь только текстом нового summary, без пояснений и разметки."""


def get_summary(user_id: int, context: Context) -> str | None:
    with SessionLocal() as session:
        row = session.query(DialogSummary).filter_by(user_id=user_id, context=context).one_or_none()
        return row.summary_text if row is not None else None


async def record_message(user_id: int, context: Context) -> None:
    with SessionLocal() as session:
        row = session.query(DialogSummary).filter_by(user_id=user_id, context=context).one_or_none()
        if row is None:
            row = DialogSummary(user_id=user_id, context=context, message_count_since_update=0)
            session.add(row)
            session.flush()

        row.message_count_since_update += 1
        should_resummarize = row.message_count_since_update >= MESSAGE_THRESHOLD
        old_summary = row.summary_text
        row_id = row.id
        session.commit()

    if should_resummarize:
        await _resummarize(row_id, user_id, context, old_summary)


async def _resummarize(row_id: int, user_id: int, context: Context, old_summary: str | None) -> None:
    with SessionLocal() as session:
        recent_notes = (
            session.query(Note)
            .filter_by(user_id=user_id, context=context)
            .order_by(Note.created_at.desc())
            .limit(MESSAGE_THRESHOLD)
            .all()
        )
        recent_texts = [note.content for note in reversed(recent_notes)]

    if not recent_texts:
        with SessionLocal() as session:
            row = session.get(DialogSummary, row_id)
            row.message_count_since_update = 0
            session.commit()
        return

    prompt = (
        f"Предыдущее summary: {old_summary or '(пусто, это первое обновление)'}\n\n"
        "Новые сообщения:\n" + "\n".join(f"- {text}" for text in recent_texts)
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    new_summary = await complete(messages, model=RESUMMARIZE_MODEL)

    with SessionLocal() as session:
        row = session.get(DialogSummary, row_id)
        row.summary_text = new_summary
        row.message_count_since_update = 0
        session.commit()
