from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from core.dialog_summary import get_summary, record_message
from db.models import Context, Note, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.reply import generate_reply

CONTEXT_LABELS = {Context.work: "рабочее", Context.personal: "личное"}


def _other_context(context: Context) -> Context:
    return Context.personal if context == Context.work else Context.work


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return

        try:
            result = await classify_message(update.message.text)
            summary = get_summary(user.id, result.context)
            reply_text = await generate_reply(update.message.text, result.context, summary)
        except LLMUnavailableError as exc:
            await update.message.reply_text(str(exc))
            return

        note = Note(user_id=user.id, content=update.message.text, context=result.context)
        session.add(note)
        session.commit()
        note_id = note.id
        user_id = user.id

    await record_message(user_id, result.context)

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Это не туда", callback_data=f"toggle_context:{note_id}")]]
    )
    await update.message.reply_text(reply_text, reply_markup=keyboard)


async def handle_context_correction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    note_id = int(query.data.split(":", 1)[1])

    with SessionLocal() as session:
        note = session.get(Note, note_id)
        owner = session.get(User, note.user_id) if note is not None else None

        if note is None or owner is None or owner.telegram_id != telegram_id:
            await query.answer("Не получилось найти запись.", show_alert=True)
            return

        note.context = _other_context(note.context)
        session.commit()
        label = CONTEXT_LABELS[note.context]

    await query.answer()
    await query.edit_message_text(f"Исправил на «{label}».")
