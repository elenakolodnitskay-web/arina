from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import voice_reply
from db.models import Base, ReplyMode, User
from llm.client import LLMUnavailableError


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(voice_reply, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "111")


def make_command_update(telegram_id: int):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.reply_text = AsyncMock()
    return update


def make_callback_update(telegram_id: int, callback_data: str):
    update = MagicMock()
    update.callback_query.from_user.id = telegram_id
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_voice_mode_command_shows_keyboard(db_session_factory, allowed_user):
    update = make_command_update(111)

    await voice_reply.voice_mode_command(update, context=None)

    update.message.reply_text.assert_awaited_once()
    assert update.message.reply_text.await_args.kwargs["reply_markup"] == voice_reply.MODE_KEYBOARD


@pytest.mark.asyncio
async def test_voice_mode_command_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_command_update(999)

    await voice_reply.voice_mode_command(update, context=None)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_handle_voice_mode_choice_sets_voice(db_session_factory, allowed_user):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    update = make_callback_update(111, voice_reply.VOICE_CALLBACK)
    await voice_reply.handle_voice_mode_choice(update, context=None)

    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=111).one()
        assert user.reply_mode == ReplyMode.voice

    assert "голосом" in update.callback_query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_voice_mode_choice_sets_text(db_session_factory, allowed_user):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True, reply_mode=ReplyMode.voice))
        session.commit()

    update = make_callback_update(111, voice_reply.TEXT_CALLBACK)
    await voice_reply.handle_voice_mode_choice(update, context=None)

    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=111).one()
        assert user.reply_mode == ReplyMode.text

    assert "текстом" in update.callback_query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_voice_mode_choice_rejects_unknown_user(db_session_factory, allowed_user):
    update = make_callback_update(999, voice_reply.VOICE_CALLBACK)

    await voice_reply.handle_voice_mode_choice(update, context=None)

    update.callback_query.answer.assert_awaited_once_with("Не нашла ваш профиль — напишите /start.", show_alert=True)
    update.callback_query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_reply_sends_text_when_mode_is_text():
    update = make_command_update(111)

    await voice_reply.send_reply(update, "Привет!", ReplyMode.text)

    update.message.reply_text.assert_awaited_once_with("Привет!")


@pytest.mark.asyncio
async def test_send_reply_passes_kwargs_in_text_mode():
    update = make_command_update(111)
    keyboard = MagicMock()

    await voice_reply.send_reply(update, "Привет!", ReplyMode.text, reply_markup=keyboard)

    update.message.reply_text.assert_awaited_once_with("Привет!", reply_markup=keyboard)


@pytest.mark.asyncio
async def test_send_reply_sends_voice_when_mode_is_voice(monkeypatch):
    update = make_command_update(111)
    update.message.reply_voice = AsyncMock()
    monkeypatch.setattr(voice_reply, "synthesize_speech", AsyncMock(return_value=b"fake wav bytes"))

    await voice_reply.send_reply(update, "Привет!", ReplyMode.voice)

    update.message.reply_voice.assert_awaited_once()
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_send_reply_ignores_kwargs_in_voice_mode(monkeypatch):
    update = make_command_update(111)
    update.message.reply_voice = AsyncMock()
    monkeypatch.setattr(voice_reply, "synthesize_speech", AsyncMock(return_value=b"fake wav bytes"))

    await voice_reply.send_reply(update, "Привет!", ReplyMode.voice, reply_markup=MagicMock())

    assert "reply_markup" not in update.message.reply_voice.await_args.kwargs


@pytest.mark.asyncio
async def test_send_reply_reports_tts_unavailable_error(monkeypatch):
    update = make_command_update(111)
    update.message.reply_voice = AsyncMock()
    monkeypatch.setattr(
        voice_reply, "synthesize_speech", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    await voice_reply.send_reply(update, "Привет!", ReplyMode.voice)

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")
    update.message.reply_voice.assert_not_called()
