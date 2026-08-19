from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import tasks_flow
from core.tasks import ParsedTask
from db.models import Base, Context, Task, TaskStatus, User
from llm.classify import ClassificationResult
from llm.client import LLMUnavailableError


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(tasks_flow, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "111")


@pytest.fixture(autouse=True)
def no_real_scheduler(monkeypatch):
    monkeypatch.setattr(tasks_flow, "schedule_task_reminder", MagicMock())
    monkeypatch.setattr(tasks_flow, "cancel_task_reminder", MagicMock())


def make_command_update(telegram_id: int, args: list[str]):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args
    return update, context


@pytest.mark.asyncio
async def test_create_task_without_text_prompts_usage(db_session_factory, allowed_user):
    update, context = make_command_update(111, [])

    await tasks_flow.create_task(update, context)

    assert "/task" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_create_task_saves_and_schedules_one_off(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    parsed = ParsedTask(
        title="позвонить маме", due_at=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc), recurrence_rule=None
    )
    monkeypatch.setattr(tasks_flow, "parse_task", AsyncMock(return_value=parsed))
    monkeypatch.setattr(
        tasks_flow, "classify_message", AsyncMock(return_value=ClassificationResult(Context.personal, 0.8))
    )

    update, context = make_command_update(111, ["позвонить", "маме", "завтра", "в", "18:00"])
    await tasks_flow.create_task(update, context)

    with db_session_factory() as session:
        task = session.query(Task).one()
        assert task.title == "позвонить маме"
        assert task.context == Context.personal
        assert task.status == TaskStatus.active

    tasks_flow.schedule_task_reminder.assert_called_once()
    assert "позвонить маме" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_create_task_rejects_when_no_schedule_parsed(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    parsed = ParsedTask(title="что-то", due_at=None, recurrence_rule=None)
    monkeypatch.setattr(tasks_flow, "parse_task", AsyncMock(return_value=parsed))
    monkeypatch.setattr(
        tasks_flow, "classify_message", AsyncMock(return_value=ClassificationResult(Context.personal, 0.5))
    )

    update, context = make_command_update(111, ["что-то", "неясное"])
    await tasks_flow.create_task(update, context)

    with db_session_factory() as session:
        assert session.query(Task).count() == 0
    assert "срок" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_create_task_reports_llm_unavailable(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(tasks_flow, "parse_task", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна")))

    update, context = make_command_update(111, ["что-то"])
    await tasks_flow.create_task(update, context)

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")


def test_describe_schedule_one_off():
    task = Task(due_at=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc), recurrence_rule=None)
    assert "20.08.2026 15:00" in tasks_flow.describe_schedule(task)


def test_describe_schedule_recurring():
    task = Task(due_at=None, recurrence_rule="0 9 * * 1")
    assert "0 9 * * 1" in tasks_flow.describe_schedule(task)


@pytest.mark.asyncio
async def test_create_task_from_text_saves_and_schedules(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    parsed = ParsedTask(
        title="позвонить маме", due_at=datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc), recurrence_rule=None
    )
    monkeypatch.setattr(tasks_flow, "parse_task", AsyncMock(return_value=parsed))
    monkeypatch.setattr(
        tasks_flow, "classify_message", AsyncMock(return_value=ClassificationResult(Context.personal, 0.8))
    )

    task = await tasks_flow.create_task_from_text(user_id, "напомни позвонить маме завтра в 18:00")

    assert task is not None
    assert task.title == "позвонить маме"
    assert task.context == Context.personal
    tasks_flow.schedule_task_reminder.assert_called_once()


@pytest.mark.asyncio
async def test_create_task_from_text_returns_none_without_schedule(db_session_factory, allowed_user, monkeypatch):
    parsed = ParsedTask(title="что-то", due_at=None, recurrence_rule=None)
    monkeypatch.setattr(tasks_flow, "parse_task", AsyncMock(return_value=parsed))
    monkeypatch.setattr(
        tasks_flow, "classify_message", AsyncMock(return_value=ClassificationResult(Context.personal, 0.5))
    )

    task = await tasks_flow.create_task_from_text(1, "что-то неясное")

    assert task is None
    tasks_flow.schedule_task_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_handle_cancel_task_marks_cancelled(db_session_factory, allowed_user):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.flush()
        task = Task(user_id=user.id, title="задача", context=Context.work, status=TaskStatus.active)
        session.add(task)
        session.commit()
        task_id = task.id

    update = MagicMock()
    update.callback_query.from_user.id = 111
    update.callback_query.data = f"cancel_task:{task_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await tasks_flow.handle_cancel_task(update, context=None)

    with db_session_factory() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.cancelled

    tasks_flow.cancel_task_reminder.assert_called_once_with(task_id)
    update.callback_query.edit_message_text.assert_awaited_once_with("Отменил.")


@pytest.mark.asyncio
async def test_handle_cancel_task_rejects_foreign_task(db_session_factory, allowed_user):
    with db_session_factory() as session:
        owner = User(telegram_id=111, onboarding_completed=True)
        session.add(owner)
        session.flush()
        task = Task(user_id=owner.id, title="чужая задача", context=Context.work, status=TaskStatus.active)
        session.add(task)
        session.commit()
        task_id = task.id

    update = MagicMock()
    update.callback_query.from_user.id = 222
    update.callback_query.data = f"cancel_task:{task_id}"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await tasks_flow.handle_cancel_task(update, context=None)

    update.callback_query.edit_message_text.assert_not_called()
    with db_session_factory() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.active
