from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import relay_flow
from core.relay import ParsedRelay
from db.models import Base, User
from llm.client import LLMUnavailableError


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(relay_flow, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "111,222")


def make_text_update(telegram_id: int, text: str):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context(user_data: dict | None = None):
    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}
    return context


@pytest.mark.asyncio
async def test_start_relay_draft_prompts_start_for_unonboarded_user(db_session_factory, allowed_user):
    update = make_text_update(111, "передай @ivan, привет")
    context = make_context()

    await relay_flow.start_relay_draft(update, context, "передай @ivan, привет")

    assert "/start" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_relay_draft_reports_llm_unavailable(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        relay_flow, "parse_relay_message", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    update = make_text_update(111, "передай @ivan, привет")
    await relay_flow.start_relay_draft(update, make_context(), "передай @ivan, привет")

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")


@pytest.mark.asyncio
async def test_start_relay_draft_reports_malformed_llm_response_gracefully(
    db_session_factory, allowed_user, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(relay_flow, "parse_relay_message", AsyncMock(side_effect=ValueError("bad json")))

    update = make_text_update(111, "передай @ivan, привет")
    await relay_flow.start_relay_draft(update, make_context(), "передай @ivan, привет")

    update.message.reply_text.assert_awaited_once()
    assert "переформулировать" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_relay_draft_asks_for_username_when_missing(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        relay_flow, "parse_relay_message", AsyncMock(return_value=ParsedRelay(username=None, message="привет"))
    )

    update = make_text_update(111, "передай Ивану привет")
    await relay_flow.start_relay_draft(update, make_context(), "передай Ивану привет")

    assert "@username" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_relay_draft_rejects_unknown_recipient(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        relay_flow,
        "parse_relay_message",
        AsyncMock(return_value=ParsedRelay(username="unknown_user", message="привет")),
    )

    update = make_text_update(111, "передай @unknown_user привет")
    await relay_flow.start_relay_draft(update, make_context(), "передай @unknown_user привет")

    assert "unknown_user" in update.message.reply_text.await_args.args[0]
    assert "Не нашла" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_relay_draft_rejects_recipient_outside_whitelist(
    db_session_factory, allowed_user, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.add(User(telegram_id=999, onboarding_completed=True, username="outsider"))
        session.commit()

    monkeypatch.setattr(
        relay_flow,
        "parse_relay_message",
        AsyncMock(return_value=ParsedRelay(username="outsider", message="привет")),
    )

    update = make_text_update(111, "передай @outsider привет")
    await relay_flow.start_relay_draft(update, make_context(), "передай @outsider привет")

    assert "Не нашла" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_relay_draft_rejects_sending_to_self(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True, username="me"))
        session.commit()

    monkeypatch.setattr(
        relay_flow, "parse_relay_message", AsyncMock(return_value=ParsedRelay(username="me", message="привет"))
    )

    update = make_text_update(111, "передай @me привет")
    await relay_flow.start_relay_draft(update, make_context(), "передай @me привет")

    assert "это же вы" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_start_relay_draft_stores_pending_and_shows_confirmation(
    db_session_factory, allowed_user, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.add(User(telegram_id=222, onboarding_completed=True, username="ivan_petrov"))
        session.commit()
        recipient_id = session.query(User).filter_by(username="ivan_petrov").one().id

    monkeypatch.setattr(
        relay_flow,
        "parse_relay_message",
        AsyncMock(return_value=ParsedRelay(username="ivan_petrov", message="встреча переносится")),
    )

    update = make_text_update(111, "передай @ivan_petrov, встреча переносится")
    context = make_context()
    await relay_flow.start_relay_draft(update, context, "передай @ivan_petrov, встреча переносится")

    pending = context.user_data[relay_flow.PENDING_KEY]
    assert pending.recipient_user_id == recipient_id
    assert pending.recipient_username == "ivan_petrov"
    assert pending.message == "встреча переносится"
    assert "ivan_petrov" in update.message.reply_text.await_args.args[0]
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_handle_confirm_relay_without_pending_draft(db_session_factory, allowed_user):
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    context = make_context()

    await relay_flow.handle_confirm_relay(update, context)

    update.callback_query.answer.assert_awaited_once()
    assert update.callback_query.answer.await_args.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_handle_confirm_relay_sends_message_and_confirms(db_session_factory, allowed_user):
    with db_session_factory() as session:
        recipient = User(telegram_id=222, onboarding_completed=True, username="ivan_petrov")
        session.add(recipient)
        session.commit()
        recipient_id = recipient.id

    pending = relay_flow.PendingRelay(
        recipient_user_id=recipient_id, recipient_username="ivan_petrov", message="встреча переносится"
    )
    update = MagicMock()
    update.callback_query.from_user.id = 111
    update.callback_query.from_user.username = "sender_name"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = make_context({relay_flow.PENDING_KEY: pending})
    context.bot.send_message = AsyncMock()

    await relay_flow.handle_confirm_relay(update, context)

    context.bot.send_message.assert_awaited_once()
    assert context.bot.send_message.await_args.kwargs["chat_id"] == 222
    sent_text = context.bot.send_message.await_args.kwargs["text"]
    assert "встреча переносится" in sent_text
    assert "через Арину" in sent_text
    assert "sender_name" in sent_text
    assert relay_flow.PENDING_KEY not in context.user_data
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_reformulate_relay_clears_pending(db_session_factory, allowed_user):
    pending = relay_flow.PendingRelay(recipient_user_id=1, recipient_username="ivan", message="старое")
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = make_context({relay_flow.PENDING_KEY: pending})

    await relay_flow.handle_reformulate_relay(update, context)

    assert relay_flow.PENDING_KEY not in context.user_data
    update.callback_query.edit_message_text.assert_awaited_once()
