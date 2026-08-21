from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from config import settings
from db.models import Task, TaskStatus, User
from db.session import SessionLocal

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=settings.database_url)},
            timezone=ZoneInfo(settings.timezone),
        )
    return _scheduler


def _job_id(task_id: int) -> str:
    return f"task-{task_id}"


def schedule_task_reminder(task: Task) -> None:
    scheduler = get_scheduler()

    if task.recurrence_rule:
        trigger = CronTrigger.from_crontab(task.recurrence_rule, timezone=ZoneInfo(settings.timezone))
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
        external_id = user.telegram_id
        platform = user.platform
        is_one_off = not task.recurrence_rule

    if platform == "max":
        from max_bot.client import send_message as max_send_message

        await max_send_message(external_id, f"Напоминание: {title}")
        # MAX не поддерживает инлайн-кнопки (известное упрощение MVP-среза, см.
        # max_bot/handlers.py) — нет способа нажать «Выполнено»/«Отложить» под
        # самим напоминанием, поэтому для MAX разовое напоминание по-прежнему
        # сразу считается выполненным после отправки (старое поведение). Если
        # отправка выше упала с исключением, до этой строки выполнение не
        # дойдёт — статус не поменяется, останется active.
        if is_one_off:
            with SessionLocal() as session:
                task = session.get(Task, task_id)
                if task is not None:
                    task.status = TaskStatus.done
                    task.completed_at = datetime.now(timezone.utc)
                    session.commit()
        return

    # В Telegram разовое напоминание ждёт явного действия пользователя — кнопки
    # «Выполнено» (переиспользует тот же хендлер, что и в /tasks) и «Отложить»
    # (задача остаётся active, просто подтверждается получение). Статус больше
    # не меняется автоматически здесь — иначе кнопки были бы бессмысленны:
    # задача успела бы стать done ещё до того, как пользователь успеет нажать.
    keyboard = None
    if is_one_off:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Выполнено", callback_data=f"complete_task:{task_id}"),
                    InlineKeyboardButton("Отложить", callback_data=f"postpone_task:{task_id}"),
                ]
            ]
        )

    bot = Bot(token=settings.telegram_bot_token)
    async with bot:
        await bot.send_message(chat_id=external_id, text=f"Напоминание: {title}", reply_markup=keyboard)
