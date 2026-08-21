from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import tariff_flow
from db.models import Base, Tariff, User


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(tariff_flow, "SessionLocal", factory)
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
async def test_tariff_command_shows_current_tariff_and_keyboard(db_session_factory, allowed_user):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True, tariff=Tariff.accountant))
        session.commit()

    update = make_command_update(111)
    await tariff_flow.tariff_command(update, context=None)

    update.message.reply_text.assert_awaited_once()
    text = update.message.reply_text.await_args.args[0]
    assert "Бухгалтер" in text
    keyboard = update.message.reply_text.await_args.kwargs["reply_markup"]
    assert len(keyboard.inline_keyboard) == 3


@pytest.mark.asyncio
async def test_tariff_command_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_command_update(999)

    await tariff_flow.tariff_command(update, context=None)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_tariff_command_rejects_unknown_user(db_session_factory, allowed_user):
    update = make_command_update(111)

    await tariff_flow.tariff_command(update, context=None)

    update.message.reply_text.assert_awaited_once_with("Не нашла ваш профиль — напишите /start.")


@pytest.mark.asyncio
async def test_handle_tariff_choice_saves_selection(db_session_factory):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True, tariff=Tariff.secretary))
        session.commit()

    update = make_callback_update(111, f"{tariff_flow.CALLBACK_PREFIX}trusted")
    await tariff_flow.handle_tariff_choice(update, context=None)

    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=111).one()
        assert user.tariff == Tariff.trusted

    assert "Доверенное лицо" in update.callback_query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_tariff_choice_can_switch_back_down(db_session_factory):
    # Свободное переключение в обе стороны — не только "апгрейд".
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True, tariff=Tariff.trusted))
        session.commit()

    update = make_callback_update(111, f"{tariff_flow.CALLBACK_PREFIX}secretary")
    await tariff_flow.handle_tariff_choice(update, context=None)

    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=111).one()
        assert user.tariff == Tariff.secretary


@pytest.mark.asyncio
async def test_handle_tariff_choice_rejects_unknown_user(db_session_factory):
    update = make_callback_update(999, f"{tariff_flow.CALLBACK_PREFIX}trusted")

    await tariff_flow.handle_tariff_choice(update, context=None)

    update.callback_query.answer.assert_awaited_once_with("Не нашла ваш профиль — напишите /start.", show_alert=True)
    update.callback_query.edit_message_text.assert_not_called()
