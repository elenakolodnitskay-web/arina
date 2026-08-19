from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from telegram import Bot

from config import settings
from db.models import Task, TaskStatus, User
from db.session import SessionLocal

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)}
        )
    return _scheduler


def _job_id(task_id: int) -> str:
    return f"task-{task_id}"


def schedule_task_reminder(task: Task) -> None:
    scheduler = get_scheduler()

    if task.recurrence_rule:
        trigger = CronTrigger.from_crontab(task.recurrence_rule)
    else:
        trigger = DateTrigger(run_date=task.due_at)

    scheduler.add_job(
        send_reminder,
        trigger=trigger,
        args=[task.id],
        id=_job_id(task.id),
        replace_existing=True,
    )


def cancel_task_reminder(task_id: int) -> None:
    scheduler = get_scheduler()
    try:
        scheduler.remove_job(_job_id(task_id))
    except JobLookupError:
        pass


async def send_reminder(task_id: int) -> None:
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None or task.status != TaskStatus.active:
            return
        user = session.get(User, task.user_id)
        title = task.title
        chat_id = user.telegram_id

    bot = Bot(token=settings.telegram_bot_token)
    async with bot:
        await bot.send_message(chat_id=chat_id, text=f"Напоминание: {title}")
