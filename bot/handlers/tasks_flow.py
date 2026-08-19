from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from core.scheduler import cancel_task_reminder, schedule_task_reminder
from core.tasks import ParsedTask, parse_task
from db.models import Task, TaskStatus, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError


def _describe_schedule(parsed: ParsedTask) -> str:
    if parsed.recurrence_rule:
        return f"повторяется по расписанию ({parsed.recurrence_rule})"
    return f"напомню {parsed.due_at.strftime('%d.%m.%Y %H:%M')} (UTC)"


async def create_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if telegram_id not in settings.allowed_user_ids_list:
        return

    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text(
            "Напишите формулировку после команды, например: "
            "/task позвонить маме завтра в 18:00"
        )
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return

        try:
            parsed = await parse_task(text)
            classification = await classify_message(text)
        except LLMUnavailableError as exc:
            await update.message.reply_text(str(exc))
            return

        if parsed.due_at is None and not parsed.recurrence_rule:
            await update.message.reply_text("Не понял срок — уточните, когда напомнить.")
            return

        task = Task(
            user_id=user.id,
            title=parsed.title,
            context=classification.context,
            due_at=parsed.due_at,
            recurrence_rule=parsed.recurrence_rule,
            status=TaskStatus.active,
        )
        session.add(task)
        session.commit()
        schedule_task_reminder(task)
        title = task.title

    await update.message.reply_text(f"Записал: «{title}» — {_describe_schedule(parsed)}.")


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if telegram_id not in settings.allowed_user_ids_list:
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        tasks = (
            session.query(Task)
            .filter_by(user_id=user.id, status=TaskStatus.active)
            .order_by(Task.created_at)
            .all()
            if user is not None
            else []
        )

        if not tasks:
            await update.message.reply_text("Активных задач нет.")
            return

        for task in tasks:
            when = task.due_at.strftime("%d.%m.%Y %H:%M") if task.due_at else task.recurrence_rule
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Отменить", callback_data=f"cancel_task:{task.id}")]]
            )
            await update.message.reply_text(f"{task.title} — {when}", reply_markup=keyboard)


async def handle_cancel_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    task_id = int(query.data.split(":", 1)[1])

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        owner = session.get(User, task.user_id) if task is not None else None

        if task is None or owner is None or owner.telegram_id != telegram_id:
            await query.answer("Не получилось найти задачу.", show_alert=True)
            return

        task.status = TaskStatus.cancelled
        session.commit()

    cancel_task_reminder(task_id)
    await query.answer()
    await query.edit_message_text("Отменил.")
