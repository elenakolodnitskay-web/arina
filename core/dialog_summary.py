from db.models import Context, Note
from db.session import SessionLocal

# Фаза 19: пользователь осознанно выбрал «хранить всё, никогда не сжимать» вместо
# LLM-пересуммаризации (которая теряла детали). Полная история остаётся без потерь
# в Note (ничего не удаляется, кроме как через /delete_my_data) — здесь только
# отвечаем на открытый вопрос "что реально попадает в промпт": не вся история, а
# ограниченное окно последних сообщений, иначе размер/стоимость промпта росли бы
# неограниченно со временем. За пределами этого окна модель ничего не "помнит" в
# рамках одного вызова — осознанный компромисс, а не забытое ограничение (см.
# Plan.md, Фаза 19, где это решение обосновано подробнее).
MAX_RECENT_MESSAGES = 30
MAX_CONTEXT_CHARS = 8000


def get_recent_context(user_id: int, context: Context) -> str | None:
    with SessionLocal() as session:
        notes = (
            session.query(Note)
            .filter_by(user_id=user_id, context=context)
            # id как вторичный ключ сортировки: created_at может совпасть у двух
            # сообщений в одну секунду (особенно на SQLite, где у CURRENT_TIMESTAMP
            # точность только до секунды) — без этого порядок в окне нестабилен.
            .order_by(Note.created_at.desc(), Note.id.desc())
            .limit(MAX_RECENT_MESSAGES)
            .all()
        )

    if not notes:
        return None

    # notes идут от новых к старым — набираем самые свежие целиком, не разрезая
    # ни одно сообщение посередине (raw text[-N:] мог обрезать самое старое из
    # оставшихся сообщений на середине слова).
    selected: list[str] = []
    total_chars = 0
    for note in notes:
        if selected and total_chars + len(note.content) > MAX_CONTEXT_CHARS:
            break
        selected.append(note.content)
        total_chars += len(note.content)

    return "\n".join(reversed(selected))
