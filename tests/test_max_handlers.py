from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from db.models import Base, Context, EmailLog, Note, Task, Transaction, User
from llm.classify import ClassificationResult
from llm.client import LLMUnavailableError
from llm.intent import Intent
from max_bot import handlers


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(handlers, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "555")


@pytest.fixture(autouse=True)
def no_real_send(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(handlers, "send_message", mock)
    return mock


@pytest.fixture(autouse=True)
def no_real_recent_context(monkeypatch):
    monkeypatch.setattr(handlers, "get_recent_context", MagicMock(return_value=None))


@pytest.mark.asyncio
async def test_new_user_gets_onboarding_prompt(db_session_factory, allowed_user, no_real_send):
    await handlers.handle_text_message(555, "привет")

    no_real_send.assert_awaited_once()
    assert "проекты" in no_real_send.await_args.args[1]
    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=555, platform="max").one()
        assert user.onboarding_completed is False


@pytest.mark.asyncio
async def test_non_whitelisted_user_gets_rejected(db_session_factory):
    await handlers.handle_text_message(999, "привет")
    with db_session_factory() as session:
        assert session.query(User).count() == 0


@pytest.mark.asyncio
async def test_second_message_completes_onboarding(db_session_factory, allowed_user, no_real_send):
    with db_session_factory() as session:
        session.add(User(telegram_id=555, platform="max"))
        session.commit()

    await handlers.handle_text_message(555, "фрилансер, дизайн и семья")

    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=555, platform="max").one()
        assert user.onboarding_completed is True
        assert user.profile_summary == "фрилансер, дизайн и семья"
    assert "/help" in no_real_send.await_args.args[1]


@pytest.mark.asyncio
async def test_help_command(db_session_factory, allowed_user, no_real_send):
    with db_session_factory() as session:
        session.add(User(telegram_id=555, platform="max", onboarding_completed=True))
        session.commit()

    await handlers.handle_text_message(555, "/help")

    no_real_send.assert_awaited_once_with(555, handlers.HELP_TEXT)


@pytest.mark.asyncio
async def test_task_intent_routes_to_task_creation(db_session_factory, allowed_user, no_real_send, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555, platform="max", onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    monkeypatch.setattr(handlers, "detect_intent", AsyncMock(return_value=Intent.task))
    fake_task = Task(id=1, user_id=user_id, title="позвонить маме", context=Context.personal)
    monkeypatch.setattr(handlers, "create_task_from_text", AsyncMock(return_value=fake_task))
    monkeypatch.setattr(handlers, "describe_schedule", MagicMock(return_value="напомню завтра в 18:00"))

    await handlers.handle_text_message(555, "напомни позвонить маме завтра в 18:00")

    assert "позвонить маме" in no_real_send.await_args.args[1]
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_chat_intent_saves_note_and_replies(db_session_factory, allowed_user, no_real_send, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555, platform="max", onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    monkeypatch.setattr(handlers, "detect_intent", AsyncMock(return_value=Intent.chat))
    monkeypatch.setattr(
        handlers, "classify_message", AsyncMock(return_value=ClassificationResult(Context.work, 0.9))
    )
    monkeypatch.setattr(handlers, "generate_reply", AsyncMock(return_value="Записал."))

    await handlers.handle_text_message(555, "отправить отчёт клиенту")

    no_real_send.assert_awaited_once_with(555, "Записал.")
    with db_session_factory() as session:
        note = session.query(Note).filter_by(user_id=user_id).one()
        assert note.content == "отправить отчёт клиенту"


@pytest.mark.asyncio
async def test_llm_unavailable_is_reported(db_session_factory, allowed_user, no_real_send, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=555, platform="max", onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(handlers, "detect_intent", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна")))

    await handlers.handle_text_message(555, "что-то")

    no_real_send.assert_awaited_once_with(555, "сеть недоступна")


@pytest.mark.asyncio
async def test_delete_my_data_removes_everything(db_session_factory, allowed_user, no_real_send):
    with db_session_factory() as session:
        user = User(telegram_id=555, platform="max", onboarding_completed=True)
        session.add(user)
        session.flush()
        session.add(Task(user_id=user.id, title="задача", context=Context.work))
        session.add(Note(user_id=user.id, content="заметка", context=Context.work))
        session.add(Transaction(user_id=user.id, amount=100, transaction_type="expense"))
        session.add(EmailLog(user_id=user.id, recipient_email="a@b.com", subject="тема", body="текст"))
        session.commit()

    await handlers.handle_text_message(555, "/delete_my_data")

    with db_session_factory() as session:
        assert session.query(User).count() == 0
        assert session.query(Task).count() == 0
        assert session.query(Note).count() == 0
        assert session.query(Transaction).count() == 0
        assert session.query(EmailLog).count() == 0
    no_real_send.assert_awaited_once_with(555, "Все ваши данные удалены.")
