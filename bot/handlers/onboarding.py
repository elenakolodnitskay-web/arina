from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.states import OnboardingState
from config import settings
from db.models import DialogSummary, Note, Task, User
from db.session import SessionLocal


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        await update.message.reply_text(
            "Извините, доступ к Арине пока закрыт — это приватная бета по приглашениям."
        )
        return ConversationHandler.END

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is not None and user.onboarding_completed:
            await update.message.reply_text("С возвращением! Чем могу помочь?")
            return ConversationHandler.END

    await update.message.reply_text(
        "Привет! Я Арина — ваш личный ИИ-помощник в работе и личных делах.\n\n"
        "Расскажите в двух словах: чем вы занимаетесь и какие у вас основные "
        "проекты или сферы — рабочие и личные? Это поможет мне лучше понимать контекст."
    )
    return OnboardingState.AWAITING_PROFILE


async def receive_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    telegram_id = update.effective_user.id
    profile_text = update.message.text

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            user = User(telegram_id=telegram_id)
            session.add(user)
        user.profile_summary = profile_text
        user.onboarding_completed = True
        session.commit()

    await update.message.reply_text(
        "Профиль сохранён. Теперь можно просто писать мне — как в обычном чате."
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Хорошо, вернёмся к этому позже. Напишите /start, когда будете готовы.")
    return ConversationHandler.END


async def delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            await update.message.reply_text("У меня нет ваших данных.")
            return

        session.query(Task).filter_by(user_id=user.id).delete()
        session.query(Note).filter_by(user_id=user.id).delete()
        session.query(DialogSummary).filter_by(user_id=user.id).delete()
        session.delete(user)
        session.commit()

    await update.message.reply_text("Все ваши данные удалены.")
