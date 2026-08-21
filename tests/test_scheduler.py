from unittest.mock import AsyncMock, MagicMock

import pytest
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core import scheduler
from db.models import Base, Context, Task, TaskStatus, User


@pytest.fixture()
def fake_scheduler(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(scheduler, "get_scheduler", lambda: fake)
    return fake


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    yield factory
    engine.dispose()


def test_schedule_task_reminder_uses_date_trigger_for_one_off(fake_scheduler):
    task = MagicMock(id=1, recurrence_rule=None, due_at="2026-08-20T15:00:00+00:00")

    scheduler.schedule_task_reminder(task)

    fake_scheduler.add_job.assert_called_once()
    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert isinstance(kwargs["trigger"], DateTrigger)
    assert kwargs["id"] == "task-1"
    assert kwargs["args"] == [1]


def test_schedule_task_reminder_uses_cron_trigger_for_recurring(fake_scheduler):
    task = MagicMock(id=2, recurrence_rule="0 9 * * 1", due_at=None)

    scheduler.schedule_task_reminder(task)

    kwargs = fake_scheduler.add_job.call_args.kwargs
    assert isinstance(kwargs["trigger"], CronTrigger)
    assert kwargs["id"] == "task-2"
    assert str(kwargs["trigger"].timezone) == "Europe/Moscow"


def test_get_scheduler_uses_configured_timezone(monkeypatch):
    monkeypatch.setattr(scheduler, "_scheduler", None)

    sched = scheduler.get_scheduler()

    assert str(sched.timezone) == "Europe/Moscow"


def test_cancel_task_reminder_removes_job(fake_scheduler):
    scheduler.cancel_task_reminder(5)
    fake_scheduler.remove_job.assert_called_once_with("task-5")


def test_cancel_task_reminder_ignores_missing_job(fake_scheduler):
    fake_scheduler.remove_job.side_effect = JobLookupError("task-9")
    scheduler.cancel_task_reminder(9)  # не должно бросить исключение


@pytest.mark.asyncio
async def test_send_reminder_sends_message_for_active_task(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555)
        session.add(user)
        session.flush()
        task = Task(user_id=user.id, title="позвонить маме", context=Context.personal, status=TaskStatus.active)
        session.add(task)
        session.commit()
        task_id = task.id

    fake_bot = MagicMock()
    fake_bot.__aenter__ = AsyncMock(return_value=fake_bot)
    fake_bot.__aexit__ = AsyncMock(return_value=False)
    fake_bot.send_message = AsyncMock()
    monkeypatch.setattr(scheduler, "Bot", MagicMock(return_value=fake_bot))

    await scheduler.send_reminder(task_id)

    fake_bot.send_message.assert_awaited_once_with(chat_id=555, text="Напоминание: позвонить маме")


@pytest.mark.asyncio
async def test_send_reminder_marks_one_off_task_done_after_sending(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555)
        session.add(user)
        session.flush()
        task = Task(
            user_id=user.id, title="разовая", context=Context.personal, status=TaskStatus.active,
            recurrence_rule=None,
        )
        session.add(task)
        session.commit()
        task_id = task.id

    fake_bot = MagicMock()
    fake_bot.__aenter__ = AsyncMock(return_value=fake_bot)
    fake_bot.__aexit__ = AsyncMock(return_value=False)
    fake_bot.send_message = AsyncMock()
    monkeypatch.setattr(scheduler, "Bot", MagicMock(return_value=fake_bot))

    await scheduler.send_reminder(task_id)

    with db_session_factory() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.done
        assert task.completed_at is not None


@pytest.mark.asyncio
async def test_send_reminder_keeps_recurring_task_active_after_sending(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555)
        session.add(user)
        session.flush()
        task = Task(
            user_id=user.id, title="повторяющаяся", context=Context.personal, status=TaskStatus.active,
            recurrence_rule="0 9 * * 1",
        )
        session.add(task)
        session.commit()
        task_id = task.id

    fake_bot = MagicMock()
    fake_bot.__aenter__ = AsyncMock(return_value=fake_bot)
    fake_bot.__aexit__ = AsyncMock(return_value=False)
    fake_bot.send_message = AsyncMock()
    monkeypatch.setattr(scheduler, "Bot", MagicMock(return_value=fake_bot))

    await scheduler.send_reminder(task_id)

    with db_session_factory() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.active


@pytest.mark.asyncio
async def test_send_reminder_marks_done_for_max_platform_too(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=777, platform="max")
        session.add(user)
        session.flush()
        task = Task(
            user_id=user.id, title="разовая на MAX", context=Context.personal, status=TaskStatus.active,
            recurrence_rule=None,
        )
        session.add(task)
        session.commit()
        task_id = task.id

    import max_bot.client

    max_send_mock = AsyncMock()
    monkeypatch.setattr(max_bot.client, "send_message", max_send_mock)

    await scheduler.send_reminder(task_id)

    max_send_mock.assert_awaited_once_with(777, "Напоминание: разовая на MAX")
    with db_session_factory() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.done


@pytest.mark.asyncio
async def test_send_reminder_does_not_mark_done_if_sending_fails(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555)
        session.add(user)
        session.flush()
        task = Task(
            user_id=user.id, title="упавшая отправка", context=Context.personal, status=TaskStatus.active,
            recurrence_rule=None,
        )
        session.add(task)
        session.commit()
        task_id = task.id

    fake_bot = MagicMock()
    fake_bot.__aenter__ = AsyncMock(return_value=fake_bot)
    fake_bot.__aexit__ = AsyncMock(return_value=False)
    fake_bot.send_message = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(scheduler, "Bot", MagicMock(return_value=fake_bot))

    with pytest.raises(RuntimeError):
        await scheduler.send_reminder(task_id)

    with db_session_factory() as session:
        task = session.get(Task, task_id)
        assert task.status == TaskStatus.active


@pytest.mark.asyncio
async def test_send_reminder_skips_cancelled_task(db_session_factory, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=555)
        session.add(user)
        session.flush()
        task = Task(
            user_id=user.id, title="отменённая", context=Context.personal, status=TaskStatus.cancelled
        )
        session.add(task)
        session.commit()
        task_id = task.id

    fake_bot_cls = MagicMock()
    monkeypatch.setattr(scheduler, "Bot", fake_bot_cls)

    await scheduler.send_reminder(task_id)

    fake_bot_cls.assert_not_called()
