from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.states import OnboardingState
from config import settings
from db.models import EmailLog, Note, Task, Transaction, User
from db.session import SessionLocal

HELP_TEXT = (
    "Вот что я умею:\n\n"
    "— Пишите мне в свободной форме — я определяю, рабочее это или личное, и "
    "запоминаю. Если ошиблась — под ответом кнопки «Рабочее»/«Личное», поправите.\n\n"
    "— Ставьте задачи и напоминания обычным текстом («напомни мне...») — разово "
    "или регулярно, пришлю сообщение в нужное время. Список активных задач — /tasks "
    "(там же можно изменить, отменить или отметить выполненной), выполненные за "
    "последние 7 дней — /tasks_done.\n\n"
    "— Можно присылать голосовые сообщения — распознаю и обработаю их так же, как "
    "текст.\n\n"
    "— Учёт бюджета: напишите о трате или поступлении («потратила 500 в "
    "Пятёрочке») — запишу; назовите текущий баланс («баланс 5000») — запомню; "
    "попросите предупреждать при низком балансе («предупреждай, если останется "
    "меньше 2000») — сообщу в следующий раз, когда баланс окажется ниже порога. "
    "Напоминания об оплате кредита/коммуналки — обычные повторяющиеся задачи, как "
    "выше.\n\n"
    "— Документы: попросите текстом, голосом или через /document <описание> — "
    "«напиши письмо клиенту...», «составь смету расходов...». Покажу черновик на "
    "подтверждение, а после — пришлю настоящий файл: Word, Excel или PDF, смотря "
    "что подходит по смыслу.\n\n"
    "— Могу передать сообщение другому пользователю Арины по @username, если он "
    "тоже здесь зарегистрирован («передай @ivan_petrov, что встреча переносится») "
    "— покажу черновик на подтверждение и явно укажу получателю, что сообщение от "
    "вас через Арину.\n\n"
    "— Для тех, у кого нет Арины, могу отправить письмо-напоминание на email "
    "(«напиши на ivan@example.com, что оплата просрочена») — тоже с черновиком на "
    "подтверждение перед отправкой.\n\n"
    "— Помню контекст разговора, не нужно повторно объяснять то, что уже "
    "обсуждали.\n\n"
    "— /voice_mode — переключить, как отвечать: голосом или текстом (по "
    "умолчанию текстом, независимо от того, как задан вопрос).\n\n"
    "— /delete_my_data — полностью удалю все ваши данные."
)


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
            user.username = update.effective_user.username
            session.commit()
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
        user.username = update.effective_user.username
        session.commit()

    await update.message.reply_text(
        "Профиль сохранён. Теперь можно просто писать мне — как в обычном чате.\n\n"
        "Если что — напишите /help, расскажу подробнее, что умею."
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Хорошо, вернёмся к этому позже. Напишите /start, когда будете готовы.")
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id
    if telegram_id not in settings.allowed_user_ids_list:
        await update.message.reply_text(
            "Извините, доступ к Арине пока закрыт — это приватная бета по приглашениям."
        )
        return

    await update.message.reply_text(HELP_TEXT)


async def delete_my_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None:
            await update.message.reply_text("У меня нет ваших данных.")
            return

        session.query(Task).filter_by(user_id=user.id).delete()
        session.query(Note).filter_by(user_id=user.id).delete()
        session.query(Transaction).filter_by(user_id=user.id).delete()
        session.query(EmailLog).filter_by(user_id=user.id).delete()
        session.delete(user)
        session.commit()

    await update.message.reply_text("Все ваши данные удалены.")
