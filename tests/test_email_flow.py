from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import email_flow
from core.email_client import EmailUnavailableError
from core.email_relay import ParsedEmail
from db.models import Base, EmailLog, User
from llm.client import LLMUnavailableError


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(email_flow, "SessionLocal", factory)
    yield factory
    engine.dispose()


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
async def test_start_email_draft_prompts_start_for_unonboarded_user(db_session_factory):
    update = make_text_update(111, "напиши на ivan@example.com про оплату")

    await email_flow.start_email_draft(update, make_context(), "напиши на ivan@example.com про оплату")

    assert "/start" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_email_draft_reports_llm_unavailable(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        email_flow, "parse_email_message", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    update = make_text_update(111, "напиши на ivan@example.com про оплату")
    await email_flow.start_email_draft(update, make_context(), "напиши на ivan@example.com про оплату")

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")


@pytest.mark.asyncio
async def test_start_email_draft_asks_for_address_when_missing(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        email_flow,
        "parse_email_message",
        AsyncMock(return_value=ParsedEmail(email=None, subject="Тема", body="Текст")),
    )

    update = make_text_update(111, "напомни Ивану про оплату")
    await email_flow.start_email_draft(update, make_context(), "напомни Ивану про оплату")

    assert "email" in update.message.reply_text.await_args.args[0].lower()


@pytest.mark.asyncio
async def test_start_email_draft_stores_pending_and_shows_confirmation(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        email_flow,
        "parse_email_message",
        AsyncMock(
            return_value=ParsedEmail(
                email="ivan@example.com", subject="Оплата просрочена", body="Просим оплатить счёт."
            )
        ),
    )

    update = make_text_update(111, "напиши на ivan@example.com про оплату")
    context = make_context()
    await email_flow.start_email_draft(update, context, "напиши на ivan@example.com про оплату")

    pending = context.user_data[email_flow.PENDING_KEY]
    assert pending.to == "ivan@example.com"
    assert pending.subject == "Оплата просрочена"
    assert "ivan@example.com" in update.message.reply_text.await_args.args[0]
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_handle_confirm_email_without_pending_draft(db_session_factory):
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    context = make_context()

    await email_flow.handle_confirm_email(update, context)

    update.callback_query.answer.assert_awaited_once()
    assert update.callback_query.answer.await_args.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_handle_confirm_email_sends_and_logs(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    send_mock = AsyncMock()
    monkeypatch.setattr(email_flow, "send_email", send_mock)

    pending = email_flow.PendingEmail(to="ivan@example.com", subject="Оплата", body="Просим оплатить.")
    update = MagicMock()
    update.callback_query.from_user.id = 111
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = make_context({email_flow.PENDING_KEY: pending})

    await email_flow.handle_confirm_email(update, context)

    send_mock.assert_awaited_once_with("ivan@example.com", "Оплата", "Просим оплатить.")
    assert email_flow.PENDING_KEY not in context.user_data
    with db_session_factory() as session:
        log = session.query(EmailLog).one()
        assert log.recipient_email == "ivan@example.com"
        assert log.subject == "Оплата"
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "ivan@example.com" in update.callback_query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_confirm_email_reports_send_failure_without_logging(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        email_flow, "send_email", AsyncMock(side_effect=EmailUnavailableError("не настроено"))
    )

    pending = email_flow.PendingEmail(to="ivan@example.com", subject="Оплата", body="Текст")
    update = MagicMock()
    update.callback_query.from_user.id = 111
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = make_context({email_flow.PENDING_KEY: pending})

    await email_flow.handle_confirm_email(update, context)

    update.callback_query.edit_message_text.assert_awaited_once_with("не настроено")
    with db_session_factory() as session:
        assert session.query(EmailLog).count() == 0


@pytest.mark.asyncio
async def test_handle_reformulate_email_clears_pending(db_session_factory):
    pending = email_flow.PendingEmail(to="ivan@example.com", subject="старое", body="старый текст")
    update = MagicMock()
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    context = make_context({email_flow.PENDING_KEY: pending})

    await email_flow.handle_reformulate_email(update, context)

    assert email_flow.PENDING_KEY not in context.user_data
    update.callback_query.edit_message_text.assert_awaited_once()
