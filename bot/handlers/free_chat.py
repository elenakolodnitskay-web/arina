import asyncio

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.documents_flow import start_document_draft
from bot.handlers.email_flow import start_email_draft
from bot.handlers.finance_flow import record_finance_message
from bot.handlers.relay_flow import start_relay_draft
from bot.handlers.tasks_flow import (
    EDIT_PENDING_KEY,
    apply_task_edit,
    create_task_from_text,
    describe_schedule,
    describe_tasks_for_chat,
)
from config import settings
from core.dialog_summary import get_recent_context
from db.models import Context, Note, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.intent import Intent, detect_intent
from llm.reply import generate_reply
from llm.transcribe import transcribe_voice

CONTEXT_LABELS = {Context.work: "рабочее", Context.personal: "личное"}


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    await _process_text(telegram_id, update.message.text, update, context)


async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    # Голосовая заметка (микрофон) приходит как .voice, аудиофайл (например,
    # пересланный из другого чата) — как .audio. Оба распознаём одинаково.
    voice_or_audio = update.message.voice or update.message.audio
    voice_file = await context.bot.get_file(voice_or_audio.file_id)
    audio_bytes = bytes(await voice_file.download_as_bytearray())

    try:
        text = await transcribe_voice(audio_bytes)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    await _process_text(telegram_id, text, update, context)


async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит форматы сообщений без отдельного хендлера (видеосообщение-кружок,
    стикеры, фото и т.п.) — чтобы пользователь получал понятный ответ вместо
    полного молчания бота, если формат не распознан ни одним из фильтров выше.
    """
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    await update.message.reply_text(
        "Пока не умею обрабатывать такой формат сообщения — напишите текстом или "
        "пришлите голосовое (кнопка микрофона)."
    )


async def _process_text(
    telegram_id: int, text: str, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    with SessionLocal() as session:
        user = session.query(User).filter_by(telegram_id=telegram_id).one_or_none()
        if user is None or not user.onboarding_completed:
            await update.message.reply_text("Сначала пройдите короткий опрос — напишите /start.")
            return
        user_id = user.id
        profile_summary = user.profile_summary

    pending_task_id = context.user_data.pop(EDIT_PENDING_KEY, None)
    if pending_task_id is not None:
        try:
            task = await apply_task_edit(user_id, pending_task_id, text)
        except LLMUnavailableError as exc:
            await update.message.reply_text(str(exc))
            return
        except (ValueError, KeyError):
            await update.message.reply_text(
                "Не поняла ответ модели — задача осталась без изменений, попробуйте ещё раз."
            )
            return

        if task is None:
            await update.message.reply_text("Не поняла новое время — задача осталась без изменений.")
        else:
            reply = f"Обновила: «{task.title}» — {describe_schedule(task)}."
            if getattr(task, "recurrence_dropped", False):
                reply += (
                    "\n⚠️ Задача была повторяющейся, теперь это разовое напоминание — "
                    "если хотели просто сдвинуть время повтора, уточните формулировку, "
                    "например «каждый понедельник в 10:00»."
                )
            await update.message.reply_text(reply)
        return

    try:
        # detect_intent и classify_message не зависят друг от друга (оба берут на
        # вход только text) — запускаем параллельно вместо последовательных
        # обращений к модели, это и есть основная задержка ответа. Классификация
        # пригодится либо для постановки задачи (не придётся вызывать её ещё раз
        # внутри create_task_from_text), либо для обычного чата ниже — она нужна
        # почти всегда, кроме finance/document/relay/email, где расчёт впустую
        # компенсируется тем, что шёл параллельно, не добавляя задержки.
        intent, classification = await asyncio.gather(detect_intent(text), classify_message(text))

        if intent == Intent.task:
            task = await create_task_from_text(user_id, text, classification)
            if task is not None:
                await update.message.reply_text(f"Записала: «{task.title}» — {describe_schedule(task)}.")
                return
            # Модель решила, что это задача, но не смогла распознать срок/повтор —
            # не показываем "не понял срок" на нейтральное сообщение, ведём как чат.

        elif intent == Intent.tasks_view:
            await update.message.reply_text(await describe_tasks_for_chat(user_id))
            return

        elif intent == Intent.finance:
            finance_reply = await record_finance_message(user_id, text)
            if finance_reply is not None:
                await update.message.reply_text(finance_reply)
                return
            # Модель решила, что это про деньги, но не смогла разобрать сумму/тип —
            # так же, как с task, ведём как обычный чат вместо "не понял".

        elif intent == Intent.document:
            # В отличие от task/finance, здесь нет случая "не смогла разобрать" —
            # generate_document всегда выдаёт какой-то черновик на подтверждение
            # (ошибки сети start_document_draft уже обрабатывает сама).
            await start_document_draft(update, context, text)
            return

        elif intent == Intent.relay:
            # start_relay_draft сама отвечает пользователю в любом исходе (нет
            # @username, получатель не найден, всё ок) — ошибки сети тоже сама.
            await start_relay_draft(update, context, text)
            return

        elif intent == Intent.email:
            # Аналогично relay — start_email_draft сама отвечает на любой исход.
            await start_email_draft(update, context, text)
            return

        result = classification
        recent_context = get_recent_context(user_id, result.context)
        reply_text = await generate_reply(text, result.context, recent_context, profile_summary)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return
    except (ValueError, KeyError):
        await update.message.reply_text("Не поняла ответ модели — попробуйте переформулировать.")
        return

    with SessionLocal() as session:
        note = Note(user_id=user_id, content=text, context=result.context)
        session.add(note)
        session.commit()
        note_id = note.id

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Рабочее", callback_data=f"set_context:{note_id}:work"),
                InlineKeyboardButton("Личное", callback_data=f"set_context:{note_id}:personal"),
            ]
        ]
    )
    await update.message.reply_text(reply_text, reply_markup=keyboard)


async def handle_context_correction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    telegram_id = query.from_user.id
    _, note_id_str, new_context_value = query.data.split(":", 2)
    note_id = int(note_id_str)
    new_context = Context(new_context_value)

    with SessionLocal() as session:
        note = session.get(Note, note_id)
        owner = session.get(User, note.user_id) if note is not None else None

        if note is None or owner is None or owner.telegram_id != telegram_id:
            await query.answer("Не получилось найти запись.", show_alert=True)
            return

        note.context = new_context
        session.commit()
        label = CONTEXT_LABELS[new_context]

    await query.answer(f"Отмечено как «{label}».")
