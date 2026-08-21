import asyncio

from bot.handlers.onboarding import HELP_TEXT
from bot.handlers.tasks_flow import create_task_from_text, describe_schedule, describe_tasks_for_chat
from config import settings
from core.dialog_summary import get_recent_context, get_recent_note_ids
from core.semantic_memory import find_relevant_notes
from core.tariffs import TARIFF_LABELS
from db.models import EmailLog, Note, Task, Transaction, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.embeddings import get_embedding_or_none
from llm.intent import Intent, detect_intent
from llm.onboarding_greeting import generate_onboarding_greeting
from llm.reply import generate_reply
from max_bot.client import send_message

PLATFORM = "max"

# MVP-срез поддержки MAX (добавлена 2026-08-20, вне пронумерованных фаз плана):
# переиспользует ту же бизнес-логику, что и Telegram (llm/, core/, db/), но пока без
# инлайн-кнопок — а значит без всего, что требует подтверждения черновика кнопкой:
# /tasks (редактирование/отмена), /document, пересылки по @username (Фаза 17) и
# email-напоминаний (Фаза 18). Учёт бюджета (Фаза 14) тоже не подключён. detect_intent
# всё равно может вернуть finance/document/relay/email на MAX-сообщении — ниже
# обрабатываются только Intent.task и Intent.tasks_view (оба не требуют кнопок —
# tasks_view вообще read-only), остальные намерения тихо уходят в обычный чат (тот
# же graceful fallback, что и у task при нераспознанном сроке). У MAX нет команды
# /tasks вовсе — tasks_view здесь особенно ценен: единственный способ посмотреть
# список задач. Пока MAX не запущен (MAX_BOT_TOKEN не задан), это не имеет живого
# эффекта. Основной путь на MAX сейчас: онбординг + свободный чат с
# автоклассификацией + постановка/просмотр задач/напоминаний естественным языком.
# Голосовой режим ответа (Фаза 26, /voice_mode) на MAX тоже не подключён — здесь
# нет клиента для отправки голосовых сообщений (send_message шлёт только текст),
# поэтому reply_mode пользователя на MAX-сообщениях не проверяется, ответ всегда
# текстом независимо от сохранённого выбора в Telegram. Тарифы (Фаза 28) — сам
# факт тарифа и рекомендация при онбординге работают одинаково на обеих
# платформах, но команды /tariff на MAX нет (нужны инлайн-кнопки для выбора,
# которых здесь пока нет) — переключить тариф на MAX сейчас нельзя, только
# посмотреть рекомендованный в приветствии.
# См. Plan.md.


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

        just_onboarded = not user.onboarding_completed
        if just_onboarded:
            user.profile_summary = text
            user.onboarding_completed = True
            session.commit()

        user_id = user.id
        profile_summary = user.profile_summary

    if just_onboarded:
        await _send_onboarding_greeting(external_user_id, user_id, text)
        return

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
        intent, result, query_embedding = await asyncio.gather(
            detect_intent(text), classify_message(text), get_embedding_or_none(text)
        )

        if intent == Intent.task:
            task = await create_task_from_text(user_id, text, result)
            if task is not None:
                await send_message(
                    external_user_id, f"Записала: «{task.title}» — {describe_schedule(task)}."
                )
                return

        if intent == Intent.tasks_view:
            await send_message(external_user_id, await describe_tasks_for_chat(user_id))
            return

        recent_context = get_recent_context(user_id, result.context)
        relevant_notes = None
        if query_embedding is not None:
            recent_ids = get_recent_note_ids(user_id, result.context)
            relevant_notes = find_relevant_notes(user_id, result.context, query_embedding, recent_ids)
        reply_text = await generate_reply(
            text, result.context, recent_context, profile_summary, relevant_notes
        )
    except LLMUnavailableError as exc:
        await send_message(external_user_id, str(exc))
        return
    except (ValueError, KeyError):
        await send_message(external_user_id, "Не поняла ответ модели — попробуйте переформулировать.")
        return

    with SessionLocal() as session:
        session.add(Note(user_id=user_id, content=text, context=result.context, embedding=query_embedding))
        session.commit()

    await send_message(external_user_id, reply_text)


async def _send_onboarding_greeting(external_user_id: int, user_id: int, profile_text: str) -> None:
    """Персональное приветствие (Фаза 28) — та же логика, что в
    bot/handlers/onboarding.py::receive_profile, продублирована здесь: профиль уже
    сохранён к моменту вызова, если генерация не удалась — статичный текст, тариф
    не трогаем (остаётся server_default='trusted', полный доступ)."""
    try:
        greeting, recommended_tariff = await generate_onboarding_greeting(profile_text)
    except (LLMUnavailableError, ValueError, KeyError):
        await send_message(
            external_user_id,
            "Профиль сохранён. Теперь можно просто писать мне — как в обычном чате.\n\n"
            "Если что — напишите /help, расскажу подробнее, что умею.",
        )
        return

    with SessionLocal() as session:
        user = session.get(User, user_id)
        user.tariff = recommended_tariff
        session.commit()

    tariff_note = f"Тариф: «{TARIFF_LABELS[recommended_tariff]}»."
    await send_message(external_user_id, f"{greeting}\n\n{tariff_note}")


async def _delete_my_data(external_user_id: int, user_id: int) -> None:
    with SessionLocal() as session:
        session.query(Task).filter_by(user_id=user_id).delete()
        session.query(Note).filter_by(user_id=user_id).delete()
        session.query(Transaction).filter_by(user_id=user_id).delete()
        session.query(EmailLog).filter_by(user_id=user_id).delete()
        session.query(User).filter_by(id=user_id).delete()
        session.commit()

    await send_message(external_user_id, "Все ваши данные удалены.")
