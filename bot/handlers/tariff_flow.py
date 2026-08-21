from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import settings
from core.tariffs import TARIFF_DESCRIPTIONS, TARIFF_LABELS, TARIFF_ORDER
from db.models import Tariff, User
from db.session import SessionLocal

CALLBACK_PREFIX = "tariff:"


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(TARIFF_LABELS[t], callback_data=f"{CALLBACK_PREFIX}{t.value}")] for t in TARIFF_ORDER]
    )


def _overview_text(current: Tariff) -> str:
    lines = [f"Сейчас у вас тариф «{TARIFF_LABELS[current]}». Доступные тарифы:\n"]
    for tariff in TARIFF_ORDER:
        marker = " ← текущий" if tariff == current else ""
        lines.append(f"«{TARIFF_LABELS[tariff]}»{marker} — {TARIFF_DESCRIPTIONS[tariff]}")
    lines.append(
        "\nПереключение бесплатное и в любую сторону — тариф сейчас определяет "
        "не оплату, а то, какими функциями вы хотите пользоваться."
    )
    return "\n".join(lines)


async def tariff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if telegram_id not in settings.allowed_user_ids_list:
        return

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            await update.message.reply_text("Не нашла ваш профиль — напишите /start.")
            return
        current = user.tariff

    await update.message.reply_text(_overview_text(current), reply_markup=_keyboard())


async def handle_tariff_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    tariff = Tariff(query.data.removeprefix(CALLBACK_PREFIX))

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            await query.answer("Не нашла ваш профиль — напишите /start.", show_alert=True)
            return
        user.tariff = tariff
        session.commit()

    await query.answer()
    await query.edit_message_text(f"Готово — тариф «{TARIFF_LABELS[tariff]}».")
