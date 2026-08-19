from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import dialog_summary
from db.models import Base, Context, DialogSummary, Note, User


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


def test_get_summary_returns_none_when_no_row(db_session_factory, user_id):
    assert dialog_summary.get_summary(user_id, Context.work) is None


@pytest.mark.asyncio
async def test_record_message_increments_counter_without_resummarizing(
    db_session_factory, user_id, monkeypatch
):
    fake_complete = AsyncMock()
    monkeypatch.setattr(dialog_summary, "complete", fake_complete)

    for _ in range(dialog_summary.MESSAGE_THRESHOLD - 1):
        await dialog_summary.record_message(user_id, Context.work)

    fake_complete.assert_not_called()
    with db_session_factory() as session:
        row = session.query(DialogSummary).filter_by(user_id=user_id, context=Context.work).one()
        assert row.message_count_since_update == dialog_summary.MESSAGE_THRESHOLD - 1
        assert row.summary_text is None


@pytest.mark.asyncio
async def test_record_message_resummarizes_at_threshold(db_session_factory, user_id, monkeypatch):
    monkeypatch.setattr(dialog_summary, "complete", AsyncMock(return_value="новое краткое summary"))

    with db_session_factory() as session:
        for text in ["первое сообщение", "второе сообщение"]:
            session.add(Note(user_id=user_id, content=text, context=Context.work))
        session.commit()

    for _ in range(dialog_summary.MESSAGE_THRESHOLD):
        await dialog_summary.record_message(user_id, Context.work)

    with db_session_factory() as session:
        row = session.query(DialogSummary).filter_by(user_id=user_id, context=Context.work).one()
        assert row.summary_text == "новое краткое summary"
        assert row.message_count_since_update == 0

    assert dialog_summary.get_summary(user_id, Context.work) == "новое краткое summary"


@pytest.mark.asyncio
async def test_record_message_resets_counter_without_llm_call_if_no_notes(
    db_session_factory, user_id, monkeypatch
):
    fake_complete = AsyncMock()
    monkeypatch.setattr(dialog_summary, "complete", fake_complete)

    for _ in range(dialog_summary.MESSAGE_THRESHOLD):
        await dialog_summary.record_message(user_id, Context.work)

    fake_complete.assert_not_called()
    with db_session_factory() as session:
        row = session.query(DialogSummary).filter_by(user_id=user_id, context=Context.work).one()
        assert row.message_count_since_update == 0
        assert row.summary_text is None


@pytest.mark.asyncio
async def test_contexts_are_tracked_separately(db_session_factory, user_id, monkeypatch):
    monkeypatch.setattr(dialog_summary, "complete", AsyncMock())

    await dialog_summary.record_message(user_id, Context.work)
    await dialog_summary.record_message(user_id, Context.personal)
    await dialog_summary.record_message(user_id, Context.personal)

    with db_session_factory() as session:
        work_row = session.query(DialogSummary).filter_by(user_id=user_id, context=Context.work).one()
        personal_row = session.query(DialogSummary).filter_by(user_id=user_id, context=Context.personal).one()
        assert work_row.message_count_since_update == 1
        assert personal_row.message_count_since_update == 2
