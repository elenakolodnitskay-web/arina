from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from telegram.ext import ConversationHandler

from bot.handlers import onboarding
from bot.states import OnboardingState
from config import settings
from db.models import Base, User


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(onboarding, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    monkeypatch.setattr(settings, "allowed_user_ids", "111")


def make_update(telegram_id: int, text: str | None = None, username: str | None = None):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.effective_user.username = username
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_start_rejects_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_update(telegram_id=999)

    result = await onboarding.start(update, context=None)

    assert result == ConversationHandler.END
    update.message.reply_text.assert_awaited_once()
    assert "закрыт" in update.message.reply_text.await_args.args[0]
    with db_session_factory() as session:
        assert session.query(User).count() == 0


@pytest.mark.asyncio
async def test_start_greets_new_whitelisted_user(db_session_factory, allowed_user):
    update = make_update(telegram_id=111)

    result = await onboarding.start(update, context=None)

    assert result == OnboardingState.AWAITING_PROFILE
    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_welcomes_back_completed_user(db_session_factory, allowed_user):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    update = make_update(telegram_id=111)
    result = await onboarding.start(update, context=None)

    assert result == ConversationHandler.END
    assert "возвращением" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_refreshes_username_for_returning_user(db_session_factory, allowed_user):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True, username="old_name"))
        session.commit()

    update = make_update(telegram_id=111, username="new_name")
    await onboarding.start(update, context=None)

    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=111).one()
        assert user.username == "new_name"


@pytest.mark.asyncio
async def test_receive_profile_saves_encrypted_profile(db_session_factory, allowed_user):
    update = make_update(
        telegram_id=111, text="фрилансер, веду проекты по дизайну и личные дела семьи", username="ivan_petrov"
    )

    result = await onboarding.receive_profile(update, context=None)

    assert result == ConversationHandler.END
    with db_session_factory() as session:
        user = session.query(User).filter_by(telegram_id=111).one()
        assert user.onboarding_completed is True
        assert user.profile_summary == "фрилансер, веду проекты по дизайну и личные дела семьи"
        assert user.username == "ivan_petrov"

        raw_value = session.connection().exec_driver_sql(
            "select profile_summary from users where id = ?", (user.id,)
        ).scalar_one()
        assert raw_value != "фрилансер, веду проекты по дизайну и личные дела семьи"

    assert "/help" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_help_command_sends_help_text_for_allowed_user(db_session_factory, allowed_user):
    update = make_update(telegram_id=111)

    await onboarding.help_command(update, context=None)

    update.message.reply_text.assert_awaited_once_with(onboarding.HELP_TEXT)


@pytest.mark.asyncio
async def test_help_command_rejects_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_update(telegram_id=999)

    await onboarding.help_command(update, context=None)

    assert "закрыт" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_delete_my_data_removes_user_and_related_rows(db_session_factory, allowed_user):
    from db.models import Context, EmailLog, Note, Task, Transaction

    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.flush()
        session.add(Task(user_id=user.id, title="задача", context=Context.personal))
        session.add(Note(user_id=user.id, content="заметка", context=Context.personal))
        session.add(Transaction(user_id=user.id, amount=500, transaction_type="expense"))
        session.add(EmailLog(user_id=user.id, recipient_email="a@b.com", subject="тема", body="текст"))
        session.commit()

    update = make_update(telegram_id=111)
    await onboarding.delete_my_data(update, context=None)

    with db_session_factory() as session:
        assert session.query(User).count() == 0
        assert session.query(Task).count() == 0
        assert session.query(Note).count() == 0
        assert session.query(Transaction).count() == 0
        assert session.query(EmailLog).count() == 0
    assert "удалены" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_delete_my_data_for_unknown_user(db_session_factory, allowed_user):
    update = make_update(telegram_id=111)

    await onboarding.delete_my_data(update, context=None)

    assert "нет ваших данных" in update.message.reply_text.await_args.args[0]
