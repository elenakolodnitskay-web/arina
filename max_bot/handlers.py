import asyncio

from bot.handlers.onboarding import HELP_TEXT
from bot.handlers.tasks_flow import create_task_from_text, describe_schedule
from config import settings
from core.dialog_summary import get_recent_context
from db.models import EmailLog, Note, Task, Transaction, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.intent import Intent, detect_intent
from llm.reply import generate_reply
from max_bot.client import send_message

PLATFORM = "max"

# MVP-срез поддержки MAX (добавлена 2026-08-20, вне пронумерованных фаз плана):
# переиспользует ту же бизнес-логику, что и Telegram (llm/, core/, db/), но пока без
# инлайн-кнопок — а значит без всего, что требует подтверждения черновика кнопкой:
# /tasks (редактирование/отмена), /document, пересылки по @username (Фаза 17) и
# email-напоминаний (Фаза 18). Учёт бюджета (Фаза 14) тоже не подключён. detect_intent
# всё равно может вернуть finance/document/relay/email на MAX-сообщении — ниже
# обрабатывается только Intent.task, остальные намерения тихо уходят в обычный чат
# (тот же graceful fallback, что и у task при нераспознанном сроке). Пока MAX не
# запущен (MAX_BOT_TOKEN не задан), это не имеет живого эффекта. Основной путь на
# MAX сейчас: онбординг + свободный чат с автоклассификацией + постановка
# задач/напоминаний естественным языком. См. Plan.md.


async def handle_text_message(external_user_id: int, text: str) -> None:
    with SessionLocal() as session:
        user = (
            session.query(User)
            .filter_by(telegram_id=external_user_id, platform=PLATFORM)
            .one_or_none()
        )

        if user is None:
            if external_user_id not in settings.allowed_user_ids_list:
                await send_message(
                    external_user_id,
                    "Извините, доступ к Арине пока закрыт — это приватная бета по приглашениям.",
                )
                return
            session.add(User(telegram_id=external_user_id, platform=PLATFORM))
            session.commit()
            await send_message(
                external_user_id,
                "Привет! Я Арина — ваш личный ИИ-помощник в работе и личных делах.\n\n"
                "Расскажите в двух словах: чем вы занимаетесь и какие у вас основные "
                "проекты или сферы — рабочие и личные? Это поможет мне лучше понимать контекст.",
            )
            return

        if not user.onboarding_completed:
            user.profile_summary = text
            user.onboarding_completed = True
            session.commit()
            await send_message(
                external_user_id,
                "Профиль сохранён. Теперь можно просто писать мне — как в обычном чате.\n\n"
                "Если что — напишите /help, расскажу подробнее, что умею.",
            )
            return

        user_id = user.id
        profile_summary = user.profile_summary

    stripped = text.strip()
    if stripped == "/help":
        await send_message(external_user_id, HELP_TEXT)
        return
    if stripped == "/delete_my_data":
        await _delete_my_data(external_user_id, user_id)
        return

    try:
        # detect_intent и classify_message независимы друг от друга — запускаем
        # параллельно вместо последовательных обращений к модели (тот же приём,
        # что в bot/handlers/free_chat.py).
        intent, result = await asyncio.gather(detect_intent(text), classify_message(text))

        if intent == Intent.task:
            task = await create_task_from_text(user_id, text, result)
            if task is not None:
                await send_message(
                    external_user_id, f"Записала: «{task.title}» — {describe_schedule(task)}."
                )
                return

        recent_context = get_recent_context(user_id, result.context)
        reply_text = await generate_reply(text, result.context, recent_context, profile_summary)
    except LLMUnavailableError as exc:
        await send_message(external_user_id, str(exc))
        return
    except (ValueError, KeyError):
        await send_message(external_user_id, "Не поняла ответ модели — попробуйте переформулировать.")
        return

    with SessionLocal() as session:
        session.add(Note(user_id=user_id, content=text, context=result.context))
        session.commit()

    await send_message(external_user_id, reply_text)


async def _delete_my_data(external_user_id: int, user_id: int) -> None:
    with SessionLocal() as session:
        session.query(Task).filter_by(user_id=user_id).delete()
        session.query(Note).filter_by(user_id=user_id).delete()
        session.query(Transaction).filter_by(user_id=user_id).delete()
        session.query(EmailLog).filter_by(user_id=user_id).delete()
        session.query(User).filter_by(id=user_id).delete()
        session.commit()

    await send_message(external_user_id, "Все ваши данные удалены.")
