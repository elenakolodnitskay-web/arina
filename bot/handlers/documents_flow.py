from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from db.models import Note, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.documents import generate_document

PENDING_KEY = "pending_document"

CONFIRM_CALLBACK = "confirm_document"
REFORMULATE_CALLBACK = "reformulate_document"

CONFIRMATION_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Подтвердить", callback_data=CONFIRM_CALLBACK),
            InlineKeyboardButton("Переформулировать", callback_data=REFORMULATE_CALLBACK),
        ]
    ]
)


async def create_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if telegram_id not in settings.allowed_user_ids_list:
        return

    description = " ".join(context.args) if context.args else ""
    if not description:
        await update.message.reply_text(
            "Опишите, что нужно написать, после команды, например: "
            "/document письмо клиенту с переносом встречи на пятницу"
        )
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return

    try:
        draft = await generate_document(description)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    context.user_data[PENDING_KEY] = draft
    await update.message.reply_text(
        f"Черновик — это ещё не готовый текст, проверьте перед использованием:\n\n{draft}",
        reply_markup=CONFIRMATION_KEYBOARD,
    )


async def handle_confirm_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    draft = context.user_data.get(PENDING_KEY)

    if draft is None:
        await query.answer("Черновик уже не актуален.", show_alert=True)
        return

    telegram_id = query.from_user.id
    try:
        classification = await classify_message(draft)
    except LLMUnavailableError as exc:
        await query.answer()
        await query.edit_message_text(str(exc))
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            await query.answer("Не нашёл ваш профиль — напишите /start.", show_alert=True)
            return
        note = Note(user_id=user.id, content=draft, context=classification.context)
        session.add(note)
        session.commit()

    context.user_data.pop(PENDING_KEY, None)
    await query.answer()
    await query.edit_message_text(f"Подтверждено и сохранено.\n\n{draft}")


async def handle_reformulate_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    context.user_data.pop(PENDING_KEY, None)
    await query.answer()
    await query.edit_message_text(
        "Хорошо, черновик отменён. Опишите ещё раз, что нужно написать: /document <описание>"
    )
