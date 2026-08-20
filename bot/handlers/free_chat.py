from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.tasks_flow import EDIT_PENDING_KEY, apply_task_edit, create_task_from_text, describe_schedule
from config import settings
from core.dialog_summary import get_summary, record_message
from db.models import Context, Note, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.intent import Intent, detect_intent
from llm.reply import generate_reply
from llm.transcribe import transcribe_voice

CONTEXT_LABELS = {Context.work: "рабочее", Context.personal: "личное"}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    await _process_text(telegram_id, update.message.text, update, context)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    voice_file = await context.bot.get_file(update.message.voice.file_id)
    audio_bytes = bytes(await voice_file.download_as_bytearray())

    try:
        text = await transcribe_voice(audio_bytes)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    await _process_text(telegram_id, text, update, context)


async def _process_text(
    telegram_id: int, text: str, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return
        user_id = user.id

    pending_task_id = context.user_data.pop(EDIT_PENDING_KEY, None)
    if pending_task_id is not None:
        try:
            task = await apply_task_edit(user_id, pending_task_id, text)
        except LLMUnavailableError as exc:
            await update.message.reply_text(str(exc))
            return

        if task is None:
            await update.message.reply_text("Не понял новое время — задача осталась без изменений.")
        else:
            await update.message.reply_text(f"Обновил: «{task.title}» — {describe_schedule(task)}.")
        return

    try:
        intent = await detect_intent(text)

        if intent == Intent.task:
            task = await create_task_from_text(user_id, text)
            if task is not None:
                await update.message.reply_text(f"Записал: «{task.title}» — {describe_schedule(task)}.")
                return
            # Модель решила, что это задача, но не смогла распознать срок/повтор —
            # не показываем "не понял срок" на нейтральное сообщение, ведём как чат.

        result = await classify_message(text)
        summary = get_summary(user_id, result.context)
        reply_text = await generate_reply(text, result.context, summary)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    with SessionLocal() as session:
        note = Note(user_id=user_id, content=text, context=result.context)
        session.add(note)
        session.commit()
        note_id = note.id

    await record_message(user_id, result.context)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Рабочее", callback_data=f"set_context:{note_id}:work"),
                InlineKeyboardButton("Личное", callback_data=f"set_context:{note_id}:personal"),
            ]
        ]
    )
    await update.message.reply_text(reply_text, reply_markup=keyboard)


async def handle_context_correction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    _, note_id_str, new_context_value = query.data.split(":", 2)
    note_id = int(note_id_str)
    new_context = Context(new_context_value)

    with SessionLocal() as session:
        note = session.get(Note, note_id)
        owner = session.get(User, note.user_id) if note is not None else None

        if note is None or owner is None or owner.telegram_id != telegram_id:
            await query.answer("Не получилось найти запись.", show_alert=True)
            return

        note.context = new_context
        session.commit()
        label = CONTEXT_LABELS[new_context]

    await query.answer(f"Отмечено как «{label}».")
