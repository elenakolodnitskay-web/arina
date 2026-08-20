import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import dialog_summary
from db.models import Base, Context, Note, User


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(dialog_summary, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def user_id(db_session_factory):
    with db_session_factory() as session:
        user = User(telegram_id=111)
        session.add(user)
        session.commit()
        return user.id


def test_get_recent_context_returns_none_without_notes(db_session_factory, user_id):
    assert dialog_summary.get_recent_context(user_id, Context.work) is None


def test_get_recent_context_returns_notes_in_chronological_order(db_session_factory, user_id):
    with db_session_factory() as session:
        for text in ["первое", "второе", "третье"]:
            session.add(Note(user_id=user_id, content=text, context=Context.work))
        session.commit()

    result = dialog_summary.get_recent_context(user_id, Context.work)

    assert result == "первое\nвторое\nтретье"


def test_get_recent_context_keeps_contexts_separate(db_session_factory, user_id):
    with db_session_factory() as session:
        session.add(Note(user_id=user_id, content="рабочее сообщение", context=Context.work))
        session.add(Note(user_id=user_id, content="личное сообщение", context=Context.personal))
        session.commit()

    work_context = dialog_summary.get_recent_context(user_id, Context.work)
    personal_context = dialog_summary.get_recent_context(user_id, Context.personal)

    assert work_context == "рабочее сообщение"
    assert personal_context == "личное сообщение"


def test_get_recent_context_limits_to_max_recent_messages(db_session_factory, user_id, monkeypatch):
    monkeypatch.setattr(dialog_summary, "MAX_RECENT_MESSAGES", 3)
    with db_session_factory() as session:
        for i in range(5):
            session.add(Note(user_id=user_id, content=f"сообщение {i}", context=Context.work))
        session.commit()

    result = dialog_summary.get_recent_context(user_id, Context.work)

    assert result == "сообщение 2\nсообщение 3\nсообщение 4"


def test_get_recent_context_drops_oldest_whole_messages_over_char_budget(
    db_session_factory, user_id, monkeypatch
):
    monkeypatch.setattr(dialog_summary, "MAX_CONTEXT_CHARS", 15)
    with db_session_factory() as session:
        session.add(Note(user_id=user_id, content="старое длинное сообщение", context=Context.work))
        session.add(Note(user_id=user_id, content="новое", context=Context.work))
        session.commit()

    result = dialog_summary.get_recent_context(user_id, Context.work)

    # Старое сообщение целиком выброшено (не обрезано посередине) — остаётся
    # только то, что помещается в бюджет целыми сообщениями.
    assert result == "новое"


def test_get_recent_context_always_keeps_most_recent_message_whole(
    db_session_factory, user_id, monkeypatch
):
    monkeypatch.setattr(dialog_summary, "MAX_CONTEXT_CHARS", 5)
    with db_session_factory() as session:
        session.add(Note(user_id=user_id, content="это сообщение длиннее лимита", context=Context.work))
        session.commit()

    result = dialog_summary.get_recent_context(user_id, Context.work)

    # Даже если самое свежее сообщение само по себе больше бюджета — оно не
    # режется посередине, а входит целиком (защита от одного длинного сообщения
    # не должна ломать единственное доступное сообщение).
    assert result == "это сообщение длиннее лимита"
