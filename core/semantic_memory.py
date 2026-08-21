from db.models import Context, Note
from db.session import SessionLocal

# Фаза 27: дополняет (не заменяет) окно последних сообщений из Фазы 19
# (core/dialog_summary.py) — здесь ищутся релевантные по смыслу записи ЗА
# пределами этого окна, чтобы Арина могла вспомнить факт, упомянутый давно.
MAX_RELEVANT_NOTES = 3
# Порог отсечки по косинусному расстоянию (0 — идентичные векторы, 2 —
# противоположные). Подобран эмпирически на живых данных (см. Plan.md, Фаза 27):
# на openai/text-embedding-3-small пары "один и тот же факт разными словами"
# ложатся заметно ближе этого порога, случайные несвязанные сообщения — заметно
# дальше. Без порога order by + limit всегда возвращал бы N "наименее
# непохожих" записей, даже если ни одна реально не относится к делу.
MAX_COSINE_DISTANCE = 0.5


def find_relevant_notes(
    user_id: int, context: Context, query_embedding: list[float], exclude_ids: set[int]
) -> str | None:
    with SessionLocal() as session:
        query = session.query(Note).filter(
            Note.user_id == user_id,
            Note.context == context,
            Note.embedding.is_not(None),
            Note.embedding.cosine_distance(query_embedding) < MAX_COSINE_DISTANCE,
        )
        if exclude_ids:
            query = query.filter(Note.id.notin_(exclude_ids))
        notes = query.order_by(Note.embedding.cosine_distance(query_embedding)).limit(MAX_RELEVANT_NOTES).all()

    if not notes:
        return None

    return "\n".join(note.content for note in notes)
