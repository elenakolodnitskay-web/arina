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
# инлайн-кнопок коррекции контекста, /tasks и /document — только основной путь:
# онбординг + свободный чат с автоклассификацией + постановка задач/напоминаний
# естественным языком. См. Plan.md.


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

    stripped = text.strip()
    if stripped == "/help":
        await send_message(external_user_id, HELP_TEXT)
        return
    if stripped == "/delete_my_data":
        await _delete_my_data(external_user_id, user_id)
        return

    try:
        intent = await detect_intent(text)

        if intent == Intent.task:
            task = await create_task_from_text(user_id, text)
            if task is not None:
                await send_message(
                    external_user_id, f"Записал: «{task.title}» — {describe_schedule(task)}."
                )
                return

        result = await classify_message(text)
        recent_context = get_recent_context(user_id, result.context)
        reply_text = await generate_reply(text, result.context, recent_context)
    except LLMUnavailableError as exc:
        await send_message(external_user_id, str(exc))
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
