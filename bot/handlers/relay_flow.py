from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from core.relay import parse_relay_message
from db.models import User
from db.session import SessionLocal
from llm.client import LLMUnavailableError

PENDING_KEY = "pending_relay"

CONFIRM_CALLBACK = "confirm_relay"
REFORMULATE_CALLBACK = "reformulate_relay"

CONFIRMATION_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("Отправить", callback_data=CONFIRM_CALLBACK),
            InlineKeyboardButton("Переформулировать", callback_data=REFORMULATE_CALLBACK),
        ]
    ]
)


@dataclass
class PendingRelay:
    recipient_user_id: int
    recipient_username: str
    message: str


async def start_relay_draft(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Разбирает просьбу переслать сообщение другому пользователю Арины и
    показывает черновик на подтверждение — общая логика для свободного
    текста/голоса (bot/handlers/free_chat.py).

    Переслать можно только тем, кто уже сам пользуется Ариной (есть в whitelist и
    завершил онбординг) — Telegram не даёт боту написать первым тому, кто не
    открывал бота (платформенное ограничение, не наше решение).
    """
    telegram_id = update.effective_user.id

    with SessionLocal() as session:
        sender = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if sender is None or not sender.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return

    try:
        parsed = await parse_relay_message(text)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return
    except (ValueError, KeyError):
        await update.message.reply_text("Не поняла ответ модели — попробуйте переформулировать.")
        return

    if not parsed.username:
        await update.message.reply_text(
            "Не поняла, кому переслать — укажите получателя через @username."
        )
        return

    with SessionLocal() as session:
        # first(), не one_or_none(): username не имеет уникального ограничения в БД
        # (обновляется только на /start, см. Plan.md Фаза 17 про известное
        # отставание) — теоретически два User могут временно совпасть по этому
        # полю, если один сменил ник, а другой успел его занять. one_or_none() упал
        # бы с MultipleResultsFound; берём самую свежую запись.
        recipient = (
            session.query(User)
            .filter_by(username=parsed.username)
            .order_by(User.id.desc())
            .first()
        )

    if (
        recipient is None
        or recipient.telegram_id not in settings.allowed_user_ids_list
        or not recipient.onboarding_completed
    ):
        await update.message.reply_text(
            f"Не нашла среди пользователей Арины @{parsed.username} — переслать могу "
            "только тем, кто уже сам пользуется Ариной (иначе Telegram не даёт боту "
            "написать первым)."
        )
        return

    if recipient.telegram_id == telegram_id:
        await update.message.reply_text(
            "Это же вы — если хотели оставить заметку себе, просто напишите её мне."
        )
        return

    context.user_data[PENDING_KEY] = PendingRelay(
        recipient_user_id=recipient.id,
        recipient_username=parsed.username,
        message=parsed.message,
    )
    await update.message.reply_text(
        f"Переслать @{parsed.username} через Арину:\n\n«{parsed.message}»",
        reply_markup=CONFIRMATION_KEYBOARD,
    )


async def handle_confirm_relay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    pending: PendingRelay | None = context.user_data.get(PENDING_KEY)

    if pending is None:
        await query.answer("Черновик уже не актуален.", show_alert=True)
        return

    sender = query.from_user
    sender_label = f"@{sender.username}" if sender.username else (sender.first_name or "пользователь Арины")

    with SessionLocal() as session:
        recipient = session.get(User, pending.recipient_user_id)
        # Та же тройная проверка, что и при создании черновика (start_relay_draft) —
        # между черновиком и подтверждением получатель мог перестать быть доступным
        # (выведен из ALLOWED_USER_IDS, ещё не завершил онбординг заново и т.п.), а
        # доставка ограничена только пользователями Арины — это гарантия из
        # постановки задачи, не просто UX на момент черновика.
        if (
            recipient is None
            or recipient.telegram_id not in settings.allowed_user_ids_list
            or not recipient.onboarding_completed
        ):
            context.user_data.pop(PENDING_KEY, None)
            await query.answer("Получатель больше не доступен для пересылки.", show_alert=True)
            return
        recipient_telegram_id = recipient.telegram_id

    context.user_data.pop(PENDING_KEY, None)
    await context.bot.send_message(
        chat_id=recipient_telegram_id,
        text=f"📨 Сообщение от {sender_label} через Арину:\n\n{pending.message}",
    )
    await query.answer()
    await query.edit_message_text(f"Отправлено @{pending.recipient_username}.")


async def handle_reformulate_relay(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    context.user_data.pop(PENDING_KEY, None)
    await query.answer()
    await query.edit_message_text(
        "Хорошо, отменила. Опишите ещё раз, кому и что передать, например: "
        "«передай @ivan_petrov, что встреча переносится на пятницу»."
    )
