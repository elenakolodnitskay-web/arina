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
from bot.handlers.voice_reply import send_reply
from config import settings
from core.dialog_summary import get_recent_context, get_recent_note_ids
from core.pdf_extract import extract_text_from_pdf
from core.semantic_memory import find_relevant_notes
from core.tariffs import Feature, feature_unavailable_message, has_feature
from db.models import Context, Note, User
from db.session import SessionLocal
from llm.classify import classify_message
from llm.client import LLMUnavailableError
from llm.embeddings import get_embedding_or_none
from llm.intent import Intent, detect_intent
from llm.reply import generate_reply
from llm.transcribe import transcribe_voice
from llm.vision import extract_text_from_image

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


# Не сетевая/LLM-защита от патологически большого распознанного текста (фото
# плотного текста, многостраничный PDF) — тот же приём, что у core/pdf_extract.py
# для самого PDF: не даём одному вложению раздуть стоимость/размер промпта
# следующих шагов (detect_intent/classify_message/generate_reply и т.д.).
MAX_EXTRACTED_TEXT_CHARS = 6000


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    # photo — список размеров одного и того же снимка от меньшего к большему,
    # берём последний (наибольшее разрешение) для максимально точного распознавания.
    photo = update.message.photo[-1]
    photo_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await photo_file.download_as_bytearray())

    try:
        extracted = await extract_text_from_image(image_bytes)
    except LLMUnavailableError as exc:
        await update.message.reply_text(str(exc))
        return

    if not extracted.strip():
        await update.message.reply_text(
            "Не нашла текста на этом фото — если текст там всё же есть, попробуйте "
            "прислать более чёткое/крупное изображение."
        )
        return

    await _process_extracted_text(telegram_id, extracted[:MAX_EXTRACTED_TEXT_CHARS], update, context)


async def handle_pdf_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    telegram_id = update.effective_user.id

    if telegram_id not in settings.allowed_user_ids_list:
        return

    pdf_file = await context.bot.get_file(update.message.document.file_id)
    pdf_bytes = bytes(await pdf_file.download_as_bytearray())
    extracted = extract_text_from_pdf(pdf_bytes)

    if not extracted.strip():
        await update.message.reply_text(
            "Не нашла текста в этом PDF — похоже, это скан без текстового слоя. "
            "Попробуйте прислать как фото (страницу целиком)."
        )
        return

    await _process_extracted_text(telegram_id, extracted, update, context)


async def _process_extracted_text(
    telegram_id: int, extracted_text: str, update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Распознанный с фото/PDF текст (Фаза 30) заходит в тот же _process_text, что
    обычный текст/голос — так автоматически срабатывает нужное намерение (переслать
    через relay, оформить в документ, отправить на email) на основе подписи к
    вложению. Подпись (если есть) ставится ПЕРЕД распознанным текстом, чтобы
    detect_intent/парсеры relay-email видели инструкцию пользователя раньше самого
    содержимого — так же, как естественно строилась бы обычная текстовая просьба
    "передай @ivan: <текст>".
    """
    caption = (update.message.caption or "").strip()
    combined_text = f"{caption}\n\n{extracted_text}" if caption else extracted_text
    await _process_text(telegram_id, combined_text, update, context)


async def handle_unsupported_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ловит форматы сообщений без отдельного хендлера (видеосообщение-кружок,
    стикеры, файлы кроме PDF и т.п. — фото и PDF с Фазы 30 обрабатываются отдельно
    через handle_photo_message/handle_pdf_message) — чтобы пользователь получал
    понятный ответ вместо полного молчания бота, если формат не распознан ни одним
    из фильтров выше.
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
        reply_mode = user.reply_mode
        tariff = user.tariff

    pending_task_id = context.user_data.pop(EDIT_PENDING_KEY, None)
    if pending_task_id is not None:
        try:
            task = await apply_task_edit(user_id, pending_task_id, text)
        except LLMUnavailableError as exc:
            await send_reply(update, str(exc), reply_mode)
            return
        except (ValueError, KeyError):
            await send_reply(
                update, "Не поняла ответ модели — задача осталась без изменений, попробуйте ещё раз.", reply_mode
            )
            return

        if task is None:
            await send_reply(update, "Не поняла новое время — задача осталась без изменений.", reply_mode)
        else:
            reply = f"Обновила: «{task.title}» — {describe_schedule(task)}."
            if getattr(task, "recurrence_dropped", False):
                reply += (
                    "\n⚠️ Задача была повторяющейся, теперь это разовое напоминание — "
                    "если хотели просто сдвинуть время повтора, уточните формулировку, "
                    "например «каждый понедельник в 10:00»."
                )
            await send_reply(update, reply, reply_mode)
        return

    try:
        # detect_intent и classify_message не зависят друг от друга (оба берут на
        # вход только text) — запускаем параллельно вместо последовательных
        # обращений к модели, это и есть основная задержка ответа. Классификация
        # пригодится либо для постановки задачи (не придётся вызывать её ещё раз
        # внутри create_task_from_text), либо для обычного чата ниже — она нужна
        # почти всегда, кроме finance/document/relay/email, где расчёт впустую
        # компенсируется тем, что шёл параллельно, не добавляя задержки.
        intent, classification, query_embedding = await asyncio.gather(
            detect_intent(text), classify_message(text), get_embedding_or_none(text)
        )

        if intent == Intent.task:
            task = await create_task_from_text(user_id, text, classification)
            if task is not None:
                await send_reply(update, f"Записала: «{task.title}» — {describe_schedule(task)}.", reply_mode)
                return
            # Модель решила, что это задача, но не смогла распознать срок/повтор —
            # не показываем "не понял срок" на нейтральное сообщение, ведём как чат.

        elif intent == Intent.tasks_view:
            await send_reply(update, await describe_tasks_for_chat(user_id), reply_mode)
            return

        elif intent == Intent.finance:
            if not has_feature(tariff, Feature.finance):
                await send_reply(update, feature_unavailable_message(Feature.finance), reply_mode)
                return
            finance_reply = await record_finance_message(user_id, text)
            if finance_reply is not None:
                await send_reply(update, finance_reply, reply_mode)
                return
            # Модель решила, что это про деньги, но не смогла разобрать сумму/тип —
            # так же, как с task, ведём как обычный чат вместо "не понял".

        elif intent == Intent.document:
            if not has_feature(tariff, Feature.documents):
                await send_reply(update, feature_unavailable_message(Feature.documents), reply_mode)
                return
            # В отличие от task/finance, здесь нет случая "не смогла разобрать" —
            # generate_document всегда выдаёт какой-то черновик на подтверждение
            # (ошибки сети start_document_draft уже обрабатывает сама).
            await start_document_draft(update, context, text)
            return

        elif intent == Intent.relay:
            if not has_feature(tariff, Feature.relay):
                await send_reply(update, feature_unavailable_message(Feature.relay), reply_mode)
                return
            # start_relay_draft сама отвечает пользователю в любом исходе (нет
            # @username, получатель не найден, всё ок) — ошибки сети тоже сама.
            await start_relay_draft(update, context, text)
            return

        elif intent == Intent.email:
            if not has_feature(tariff, Feature.email):
                await send_reply(update, feature_unavailable_message(Feature.email), reply_mode)
                return
            # Аналогично relay — start_email_draft сама отвечает на любой исход.
            await start_email_draft(update, context, text)
            return

        result = classification
        recent_context = get_recent_context(user_id, result.context)
        relevant_notes = None
        if query_embedding is not None:
            recent_ids = get_recent_note_ids(user_id, result.context)
            relevant_notes = find_relevant_notes(user_id, result.context, query_embedding, recent_ids)
        reply_text = await generate_reply(
            text, result.context, recent_context, profile_summary, relevant_notes
        )
    except LLMUnavailableError as exc:
        await send_reply(update, str(exc), reply_mode)
        return
    except (ValueError, KeyError):
        await send_reply(update, "Не поняла ответ модели — попробуйте переформулировать.", reply_mode)
        return

    with SessionLocal() as session:
        note = Note(user_id=user_id, content=text, context=result.context, embedding=query_embedding)
        session.add(note)
        session.commit()
        note_id = note.id

    # Кнопки коррекции контекста доступны только вместе с текстовым ответом —
    # send_reply молча отбрасывает reply_markup в голосовом режиме (см. её
    # докстринг): нет смысла посылать активные inline-кнопки под голосовым
    # сообщением, на которое и так можно ответить текстом, чтобы поправить.
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Рабочее", callback_data=f"set_context:{note_id}:work"),
                InlineKeyboardButton("Личное", callback_data=f"set_context:{note_id}:personal"),
            ]
        ]
    )
    await send_reply(update, reply_text, reply_mode, reply_markup=keyboard)


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
