from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import free_chat
from db.models import Base, Context, Note, User
from llm.classify import ClassificationResult
from llm.client import LLMUnavailableError


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(free_chat, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "111")


@pytest.fixture(autouse=True)
def no_real_dialog_summary(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(free_chat, "record_message", mock)
    monkeypatch.setattr(free_chat, "get_summary", MagicMock(return_value=None))
    return mock


@pytest.fixture(autouse=True)
def no_real_reply(monkeypatch):
    mock = AsyncMock(return_value="сгенерированный ответ")
    monkeypatch.setattr(free_chat, "generate_reply", mock)
    return mock


def make_message_update(telegram_id: int, text: str):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_handle_message_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_message_update(telegram_id=999, text="привет")

    await free_chat.handle_message(update, context=None)

    update.message.reply_text.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_prompts_start_for_unonboarded_user(db_session_factory, allowed_user):
    update = make_message_update(telegram_id=111, text="привет")

    await free_chat.handle_message(update, context=None)

    update.message.reply_text.assert_awaited_once()
    assert "/start" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_message_saves_classified_note(
    db_session_factory, allowed_user, no_real_dialog_summary, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.work, confidence=0.9)),
    )

    update = make_message_update(telegram_id=111, text="отправить отчёт клиенту")
    await free_chat.handle_message(update, context=None)

    with db_session_factory() as session:
        note = session.query(Note).one()
        assert note.content == "отправить отчёт клиенту"
        assert note.context == Context.work

    no_real_dialog_summary.assert_awaited_once_with(user_id, Context.work)
    no_real_reply.assert_awaited_once_with("отправить отчёт клиенту", Context.work, None)

    update.message.reply_text.assert_awaited_once()
    assert update.message.reply_text.await_args.args[0] == "сгенерированный ответ"
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_handle_message_passes_existing_summary_into_reply(
    db_session_factory, allowed_user, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.personal, confidence=0.7)),
    )
    monkeypatch.setattr(free_chat, "get_summary", MagicMock(return_value="ранее обсуждали поездку"))

    update = make_message_update(telegram_id=111, text="что там с поездкой")
    await free_chat.handle_message(update, context=None)

    no_real_reply.assert_awaited_once_with("что там с поездкой", Context.personal, "ранее обсуждали поездку")


@pytest.mark.asyncio
async def test_handle_message_reports_llm_unavailable_error(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        free_chat, "classify_message", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    update = make_message_update(telegram_id=111, text="привет")
    await free_chat.handle_message(update, context=None)

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_context_correction_toggles_and_confirms(db_session_factory, allowed_user):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.flush()
        note = Note(user_id=user.id, content="что-то", context=Context.work)
        session.add(note)
        session.commit()
        note_id = note.id

    update = MagicMock()
    update.callback_query.from_user.id = 111
    update.callback_query.data = f"toggle_context:{note_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await free_chat.handle_context_correction(update, context=None)

    with db_session_factory() as session:
        note = session.get(Note, note_id)
        assert note.context == Context.personal

    update.callback_query.edit_message_text.assert_awaited_once()
    assert "личное" in update.callback_query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_context_correction_rejects_foreign_note(db_session_factory, allowed_user):
    with db_session_factory() as session:
        owner = User(telegram_id=111, onboarding_completed=True)
        session.add(owner)
        session.flush()
        note = Note(user_id=owner.id, content="приватное", context=Context.personal)
        session.add(note)
        session.commit()
        note_id = note.id

    update = MagicMock()
    update.callback_query.from_user.id = 222
    update.callback_query.data = f"toggle_context:{note_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await free_chat.handle_context_correction(update, context=None)

    update.callback_query.edit_message_text.assert_not_called()
    with db_session_factory() as session:
        note = session.get(Note, note_id)
        assert note.context == Context.personal
