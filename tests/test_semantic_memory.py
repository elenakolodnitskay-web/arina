import pytest
from sqlalchemy.orm import sessionmaker

from core import semantic_memory
from db.models import Context, Note, User
from db.session import engine

# Note.embedding.cosine_distance(...) компилируется в оператор pgvector "<=>",
# которого нет на SQLite (там тестируется весь остальной проект) — реального
# поведения поиска по смыслу без настоящего Postgres+pgvector не проверить.
# Каждый тест идёт в своей транзакции с откатом в конце (savepoint) — dev-данные
# не трогаются, как и остальные "живые" проверки в этой сессии.


@pytest.fixture()
def db_session(monkeypatch):
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection)
    session = factory()
    monkeypatch.setattr(semantic_memory, "SessionLocal", factory)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


_next_telegram_id = 999999001


def make_user(session) -> int:
    global _next_telegram_id
    user = User(telegram_id=_next_telegram_id, onboarding_completed=True)
    _next_telegram_id += 1
    session.add(user)
    session.commit()
    return user.id


def vec(value: float, dim: int = 1536) -> list[float]:
    return [value] * dim


def basis(index: int, dim: int = 1536) -> list[float]:
    """Единичный вектор вдоль одной оси — в отличие от vec() (все компоненты
    одинаковы, значит направление всегда одно и то же независимо от величины),
    basis(0) и basis(1) ортогональны (косинусное расстояние = 1), нужны там, где
    важна именно РАЗНИЦА направлений, а не просто разные числа в векторе."""
    v = [0.0] * dim
    v[index] = 1.0
    return v


def blend(weight_a: float, weight_b: float, dim: int = 1536) -> list[float]:
    v = [0.0] * dim
    v[0] = weight_a
    v[1] = weight_b
    return v


@pytest.mark.asyncio
async def test_find_relevant_notes_returns_closest_match(db_session):
    user_id = make_user(db_session)
    query = basis(0)
    close = Note(
        user_id=user_id,
        content="близкая по смыслу заметка",
        context=Context.personal,
        embedding=blend(0.95, 0.05),  # почти то же направление, что и query
    )
    far = Note(
        user_id=user_id,
        content="совсем другая тема",
        context=Context.personal,
        embedding=basis(1),  # ортогонально query — далеко по косинусу
    )
    db_session.add_all([close, far])
    db_session.commit()

    result = semantic_memory.find_relevant_notes(user_id, Context.personal, query, exclude_ids=set())

    assert result == "близкая по смыслу заметка"


@pytest.mark.asyncio
async def test_find_relevant_notes_excludes_given_ids(db_session):
    user_id = make_user(db_session)
    note = Note(user_id=user_id, content="уже в недавнем окне", context=Context.personal, embedding=vec(0.1))
    db_session.add(note)
    db_session.commit()

    result = semantic_memory.find_relevant_notes(user_id, Context.personal, vec(0.1), exclude_ids={note.id})

    assert result is None


@pytest.mark.asyncio
async def test_find_relevant_notes_ignores_notes_without_embedding(db_session):
    user_id = make_user(db_session)
    db_session.add(Note(user_id=user_id, content="старая запись без эмбеддинга", context=Context.personal))
    db_session.commit()

    result = semantic_memory.find_relevant_notes(user_id, Context.personal, vec(0.1), exclude_ids=set())

    assert result is None


@pytest.mark.asyncio
async def test_find_relevant_notes_respects_distance_threshold(db_session):
    user_id = make_user(db_session)
    # Полностью противоположный вектор — расстояние заведомо больше порога.
    unrelated = Note(user_id=user_id, content="абсолютно не по теме", context=Context.personal, embedding=vec(-0.1))
    db_session.add(unrelated)
    db_session.commit()

    result = semantic_memory.find_relevant_notes(user_id, Context.personal, vec(0.1), exclude_ids=set())

    assert result is None


@pytest.mark.asyncio
async def test_find_relevant_notes_scopes_by_user_and_context(db_session):
    user_id = make_user(db_session)
    other_user_id = make_user(db_session)
    db_session.add(Note(user_id=other_user_id, content="чужая заметка", context=Context.personal, embedding=vec(0.1)))
    db_session.add(Note(user_id=user_id, content="рабочая заметка", context=Context.work, embedding=vec(0.1)))
    db_session.commit()

    result = semantic_memory.find_relevant_notes(user_id, Context.personal, vec(0.1), exclude_ids=set())

    assert result is None


@pytest.mark.asyncio
async def test_find_relevant_notes_limits_to_max_relevant(db_session):
    user_id = make_user(db_session)
    for i in range(semantic_memory.MAX_RELEVANT_NOTES + 2):
        db_session.add(
            Note(user_id=user_id, content=f"заметка {i}", context=Context.personal, embedding=vec(0.1 + i * 0.001))
        )
    db_session.commit()

    result = semantic_memory.find_relevant_notes(user_id, Context.personal, vec(0.1), exclude_ids=set())

    assert result is not None
    assert len(result.split("\n")) == semantic_memory.MAX_RELEVANT_NOTES
