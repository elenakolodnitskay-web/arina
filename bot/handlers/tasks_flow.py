import asyncio
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from core.scheduler import cancel_task_reminder, schedule_task_reminder
from core.tasks import parse_task
from db.models import Task, TaskStatus, User
from db.session import SessionLocal
from llm.classify import ClassificationResult, classify_message
from llm.client import LLMUnavailableError

EDIT_PENDING_KEY = "pending_edit_task_id"


def _format_local(due_at) -> str:
    return due_at.astimezone(ZoneInfo(settings.timezone)).strftime("%d.%m.%Y %H:%M")


def describe_schedule(task: Task) -> str:
    if task.recurrence_rule:
        return f"повторяется по расписанию ({task.recurrence_rule})"
    return f"напомню {_format_local(task.due_at)}"


async def create_task_from_text(
    user_id: int, text: str, classification: ClassificationResult | None = None
) -> Task | None:
    """Разбирает текст через LLM, сохраняет Task и ставит напоминание в планировщик.

    Общая логика для команды /task и распознавания намерения в свободном чате
    (bot/handlers/free_chat.py) — вынесена сюда, чтобы не дублировать разбор,
    классификацию контекста и постановку в планировщик в двух местах.

    `classification`, если уже известна вызывающей стороне (free_chat.py уже
    запускает classify_message параллельно с detect_intent) — передаётся готовой,
    чтобы не делать тот же запрос к модели повторно. Если не передана — разбор
    задачи и классификация запускаются параллельно (они независимы друг от друга).

    Возвращает None, если модель не смогла распознать срок/повтор — ничего не
    сохраняет в этом случае.
    """
    if classification is None:
        parsed, classification = await asyncio.gather(parse_task(text), classify_message(text))
    else:
        parsed = await parse_task(text)

    if parsed.due_at is None and not parsed.recurrence_rule:
        return None

    with SessionLocal() as session:
        task = Task(
            user_id=user_id,
            title=parsed.title,
            context=classification.context,
            due_at=parsed.due_at,
            recurrence_rule=parsed.recurrence_rule,
            status=TaskStatus.active,
        )
        session.add(task)
        session.commit()
        schedule_task_reminder(task)
        session.refresh(task)
        return task


async def apply_task_edit(user_id: int, task_id: int, text: str) -> Task | None:
    """Переразбирает текст через LLM и обновляет существующую задачу на месте —
    время/текст/контекст, включая перепостановку в планировщик.

    Разбор задачи и классификация контекста независимы друг от друга — запускаются
    параллельно, а не по очереди.

    Возвращает None, если модель не смогла распознать срок/повтор, или если
    задача не найдена/не принадлежит пользователю — в обоих случаях задача не
    меняется.
    """
    parsed, classification = await asyncio.gather(parse_task(text), classify_message(text))

    if parsed.due_at is None and not parsed.recurrence_rule:
        return None

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            return None

        # Полный переразбор текста может не упомянуть повтор, даже если задача
        # была повторяющейся (например, «перенеси на 10:00» — про время, не про
        # то, что повтор нужно снять) — предупреждаем об этом переходе в ответе,
        # чтобы пользователь не потерял регулярное напоминание незаметно.
        recurrence_dropped = bool(task.recurrence_rule) and not parsed.recurrence_rule

        task.title = parsed.title
        task.context = classification.context
        task.due_at = parsed.due_at
        task.recurrence_rule = parsed.recurrence_rule
        session.commit()
        schedule_task_reminder(task)  # replace_existing=True переставит триггер
        session.refresh(task)
        task.recurrence_dropped = recurrence_dropped  # транзиентный атрибут, не колонка БД
        return task


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
        user_id = user.id

    try:
        task = await create_task_from_text(user_id, text)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return
    except (ValueError, KeyError):
        await update.message.reply_text("Не поняла ответ модели — попробуйте переформулировать.")
        return

    if task is None:
        await update.message.reply_text("Не поняла срок — уточните, когда напомнить.")
        return

    await update.message.reply_text(f"Записала: «{task.title}» — {describe_schedule(task)}.")


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
            when = _format_local(task.due_at) if task.due_at else task.recurrence_rule
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Изменить", callback_data=f"edit_task:{task.id}"),
                        InlineKeyboardButton("Отменить", callback_data=f"cancel_task:{task.id}"),
                    ]
                ]
            )
            await update.message.reply_text(f"{task.title} — {when}", reply_markup=keyboard)


async def handle_edit_task_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    task_id = int(query.data.split(":", 1)[1])

    with SessionLocal() as session:
        task = session.get(Task, task_id)
        owner = session.get(User, task.user_id) if task is not None else None

        if task is None or owner is None or owner.telegram_id != telegram_id:
            await query.answer("Не получилось найти задачу.", show_alert=True)
            return
        title = task.title

    context.user_data[EDIT_PENDING_KEY] = task_id
    await query.answer()
    await query.message.reply_text(
        f"Опишите новое время или текст для «{title}» — например: «завтра в 15:00» "
        "или сформулируйте задачу заново целиком."
    )


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
    await query.edit_message_text("Отменила.")
