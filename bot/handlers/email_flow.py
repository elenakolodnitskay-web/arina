from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from core.email_client import EmailUnavailableError, send_email
from core.email_relay import parse_email_message
from db.models import EmailLog, User
from db.session import SessionLocal
from llm.client import LLMUnavailableError

PENDING_KEY = "pending_email"

CONFIRM_CALLBACK = "confirm_email"
REFORMULATE_CALLBACK = "reformulate_email"

CONFIRMATION_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Отправить", callback_data=CONFIRM_CALLBACK),
            InlineKeyboardButton("Переформулировать", callback_data=REFORMULATE_CALLBACK),
        ]
    ]
)


@dataclass
class PendingEmail:
    to: str
    subject: str
    body: str


async def start_email_draft(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Разбирает просьбу отправить письмо-напоминание контакту без Арины и
    показывает черновик на подтверждение — общая логика для свободного
    текста/голоса (bot/handlers/free_chat.py).
    """
    telegram_id = update.effective_user.id

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return

    try:
        parsed = await parse_email_message(text)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    if not parsed.email:
        await update.message.reply_text(
            "Не поняла, на какой email отправить — укажите адрес явно."
        )
        return

    context.user_data[PENDING_KEY] = PendingEmail(to=parsed.email, subject=parsed.subject, body=parsed.body)
    await update.message.reply_text(
        f"Письмо на {parsed.email}\nТема: {parsed.subject}\n\n{parsed.body}",
        reply_markup=CONFIRMATION_KEYBOARD,
    )


async def handle_confirm_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    pending: PendingEmail | None = context.user_data.get(PENDING_KEY)

    if pending is None:
        await query.answer("Черновик уже не актуален.", show_alert=True)
        return

    telegram_id = query.from_user.id
    context.user_data.pop(PENDING_KEY, None)

    try:
        await send_email(pending.to, pending.subject, pending.body)
    except EmailUnavailableError as exc:
        await query.answer()
        await query.edit_message_text(str(exc))
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is not None:
            session.add(
                EmailLog(user_id=user.id, recipient_email=pending.to, subject=pending.subject, body=pending.body)
            )
            session.commit()

    await query.answer()
    await query.edit_message_text(f"Отправлено на {pending.to}.")


async def handle_reformulate_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    context.user_data.pop(PENDING_KEY, None)
    await query.answer()
    await query.edit_message_text(
        "Хорошо, отменила. Опишите ещё раз, куда и что написать, например: "
        "«напиши на ivan@example.com, что оплата просрочена»."
    )
