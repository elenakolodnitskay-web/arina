from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import free_chat
from core.tasks import ParsedTask
from db.models import Base, Context, Note, Task, User
from llm.classify import ClassificationResult
from llm.client import LLMUnavailableError
from llm.intent import Intent


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(free_chat, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "111")


@pytest.fixture(autouse=True)
def no_real_recent_context(monkeypatch):
    mock = MagicMock(return_value=None)
    monkeypatch.setattr(free_chat, "get_recent_context", mock)
    return mock


@pytest.fixture(autouse=True)
def no_real_reply(monkeypatch):
    mock = AsyncMock(return_value="сгенерированный ответ")
    monkeypatch.setattr(free_chat, "generate_reply", mock)
    return mock


@pytest.fixture(autouse=True)
def chat_intent_by_default(monkeypatch):
    # По умолчанию сообщение не похоже на задачу — большинство тестов проверяют
    # ветку обычного чата, не хотят каждый раз явно мокать detect_intent.
    mock = AsyncMock(return_value=Intent.chat)
    monkeypatch.setattr(free_chat, "detect_intent", mock)
    return mock


def make_message_update(telegram_id: int, text: str):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


def make_context(user_data: dict | None = None):
    context = MagicMock()
    context.user_data = user_data if user_data is not None else {}
    return context


@pytest.mark.asyncio
async def test_handle_message_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_message_update(telegram_id=999, text="привет")

    await free_chat.handle_message(update, make_context())

    update.message.reply_text.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_prompts_start_for_unonboarded_user(db_session_factory, allowed_user):
    update = make_message_update(telegram_id=111, text="привет")

    await free_chat.handle_message(update, make_context())

    update.message.reply_text.assert_awaited_once()
    assert "/start" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_message_saves_classified_note(
    db_session_factory, allowed_user, no_real_recent_context, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.work, confidence=0.9)),
    )

    update = make_message_update(telegram_id=111, text="отправить отчёт клиенту")
    await free_chat.handle_message(update, make_context())

    with db_session_factory() as session:
        note = session.query(Note).one()
        assert note.content == "отправить отчёт клиенту"
        assert note.context == Context.work

    no_real_recent_context.assert_called_once_with(user_id, Context.work)
    no_real_reply.assert_awaited_once_with("отправить отчёт клиенту", Context.work, None)

    update.message.reply_text.assert_awaited_once()
    assert update.message.reply_text.await_args.args[0] == "сгенерированный ответ"
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_handle_message_passes_recent_context_into_reply(
    db_session_factory, allowed_user, no_real_reply, no_real_recent_context, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.personal, confidence=0.7)),
    )
    no_real_recent_context.return_value = "вчера обсуждали поездку в отпуск"

    update = make_message_update(telegram_id=111, text="что там с поездкой")
    await free_chat.handle_message(update, make_context())

    no_real_reply.assert_awaited_once_with(
        "что там с поездкой", Context.personal, "вчера обсуждали поездку в отпуск"
    )


@pytest.mark.asyncio
async def test_handle_message_routes_task_intent_to_task_creation(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    chat_intent_by_default.return_value = Intent.task
    fake_task = Task(id=1, user_id=user_id, title="позвонить маме", context=Context.personal)
    monkeypatch.setattr(free_chat, "create_task_from_text", AsyncMock(return_value=fake_task))
    monkeypatch.setattr(free_chat, "describe_schedule", MagicMock(return_value="напомню 20.08.2026 18:00 (UTC)"))
    classify_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "classify_message", classify_mock)

    update = make_message_update(telegram_id=111, text="напомни в 20:56 позвонить маме")
    await free_chat.handle_message(update, make_context())

    free_chat.create_task_from_text.assert_awaited_once_with(user_id, "напомни в 20:56 позвонить маме")
    assert "позвонить маме" in update.message.reply_text.await_args.args[0]
    assert "напомню 20.08.2026 18:00" in update.message.reply_text.await_args.args[0]
    classify_mock.assert_not_called()
    no_real_reply.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_routes_finance_intent_to_finance_flow(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    chat_intent_by_default.return_value = Intent.finance
    finance_mock = AsyncMock(return_value="Записал расход: 500 ₽ (Пятёрочка).")
    monkeypatch.setattr(free_chat, "record_finance_message", finance_mock)
    classify_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "classify_message", classify_mock)

    update = make_message_update(telegram_id=111, text="потратила 500 в Пятёрочке")
    await free_chat.handle_message(update, make_context())

    finance_mock.assert_awaited_once()
    assert "500" in update.message.reply_text.await_args.args[0]
    classify_mock.assert_not_called()
    no_real_reply.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_routes_document_intent_to_document_draft(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    chat_intent_by_default.return_value = Intent.document
    draft_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "start_document_draft", draft_mock)
    classify_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "classify_message", classify_mock)

    update = make_message_update(telegram_id=111, text="напиши письмо клиенту про перенос встречи")
    context = make_context()
    await free_chat.handle_message(update, context)

    draft_mock.assert_awaited_once_with(update, context, "напиши письмо клиенту про перенос встречи")
    classify_mock.assert_not_called()
    no_real_reply.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_routes_relay_intent_to_relay_draft(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    chat_intent_by_default.return_value = Intent.relay
    relay_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "start_relay_draft", relay_mock)
    classify_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "classify_message", classify_mock)

    update = make_message_update(telegram_id=111, text="передай @ivan_petrov, что встреча переносится")
    context = make_context()
    await free_chat.handle_message(update, context)

    relay_mock.assert_awaited_once_with(update, context, "передай @ivan_petrov, что встреча переносится")
    classify_mock.assert_not_called()
    no_real_reply.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_routes_email_intent_to_email_draft(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    chat_intent_by_default.return_value = Intent.email
    email_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "start_email_draft", email_mock)
    classify_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "classify_message", classify_mock)

    update = make_message_update(telegram_id=111, text="напиши на ivan@example.com про оплату")
    context = make_context()
    await free_chat.handle_message(update, context)

    email_mock.assert_awaited_once_with(update, context, "напиши на ivan@example.com про оплату")
    classify_mock.assert_not_called()
    no_real_reply.assert_not_called()
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


@pytest.mark.asyncio
async def test_handle_message_falls_back_to_chat_when_finance_unparseable(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    chat_intent_by_default.return_value = Intent.finance
    monkeypatch.setattr(free_chat, "record_finance_message", AsyncMock(return_value=None))
    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.personal, confidence=0.5)),
    )

    update = make_message_update(telegram_id=111, text="что-то невнятное про деньги")
    await free_chat.handle_message(update, make_context())

    no_real_reply.assert_awaited_once()
    with db_session_factory() as session:
        assert session.query(Note).count() == 1


@pytest.mark.asyncio
async def test_handle_message_falls_back_to_chat_when_task_has_no_schedule(
    db_session_factory, allowed_user, chat_intent_by_default, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    chat_intent_by_default.return_value = Intent.task
    monkeypatch.setattr(free_chat, "create_task_from_text", AsyncMock(return_value=None))
    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.personal, confidence=0.6)),
    )

    update = make_message_update(telegram_id=111, text="надо бы созвониться с кем-то как-нибудь")
    await free_chat.handle_message(update, make_context())

    no_real_reply.assert_awaited_once()
    with db_session_factory() as session:
        assert session.query(Note).count() == 1


@pytest.mark.asyncio
async def test_handle_message_reports_llm_unavailable_error(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        free_chat, "classify_message", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    update = make_message_update(telegram_id=111, text="привет")
    await free_chat.handle_message(update, make_context())


@pytest.mark.asyncio
async def test_handle_message_applies_pending_task_edit(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.commit()
        user_id = user.id

    fake_task = Task(id=7, user_id=user_id, title="обновлённая задача", context=Context.work)
    apply_edit_mock = AsyncMock(return_value=fake_task)
    monkeypatch.setattr(free_chat, "apply_task_edit", apply_edit_mock)
    monkeypatch.setattr(free_chat, "describe_schedule", MagicMock(return_value="напомню завтра в 10:00"))
    detect_intent_mock = AsyncMock()
    monkeypatch.setattr(free_chat, "detect_intent", detect_intent_mock)

    update = make_message_update(telegram_id=111, text="завтра в 10:00")
    context = make_context({free_chat.EDIT_PENDING_KEY: 7})
    await free_chat.handle_message(update, context)

    apply_edit_mock.assert_awaited_once_with(user_id, 7, "завтра в 10:00")
    detect_intent_mock.assert_not_called()
    assert free_chat.EDIT_PENDING_KEY not in context.user_data
    assert "обновлённая задача" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_message_reports_unparseable_task_edit(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(free_chat, "apply_task_edit", AsyncMock(return_value=None))

    update = make_message_update(telegram_id=111, text="непонятно что")
    context = make_context({free_chat.EDIT_PENDING_KEY: 7})
    await free_chat.handle_message(update, context)

    assert "без изменений" in update.message.reply_text.await_args.args[0]
    with db_session_factory() as session:
        assert session.query(Note).count() == 0


def make_voice_update(telegram_id: int, file_id: str = "voice-file-id"):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.voice.file_id = file_id
    update.message.audio = None
    update.message.reply_text = AsyncMock()
    return update


def make_audio_update(telegram_id: int, file_id: str = "audio-file-id"):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.voice = None
    update.message.audio.file_id = file_id
    update.message.reply_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_handle_voice_message_transcribes_then_processes_as_text(
    db_session_factory, allowed_user, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.work, confidence=0.9)),
    )
    transcribe_mock = AsyncMock(return_value="отправить отчёт клиенту")
    monkeypatch.setattr(free_chat, "transcribe_voice", transcribe_mock)

    update = make_voice_update(telegram_id=111)
    voice_file = MagicMock()
    voice_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw ogg bytes"))
    update.effective_chat = MagicMock()
    context = make_context()
    context.bot.get_file = AsyncMock(return_value=voice_file)

    await free_chat.handle_voice_message(update, context)

    context.bot.get_file.assert_awaited_once_with("voice-file-id")
    transcribe_mock.assert_awaited_once_with(b"raw ogg bytes")
    with db_session_factory() as session:
        note = session.query(Note).one()
        assert note.content == "отправить отчёт клиенту"

    update.message.reply_text.assert_awaited_once()
    assert update.message.reply_text.await_args.args[0] == "сгенерированный ответ"


@pytest.mark.asyncio
async def test_handle_voice_message_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update = make_voice_update(telegram_id=999)
    context = make_context()
    context.bot.get_file = AsyncMock()

    await free_chat.handle_voice_message(update, context)

    context.bot.get_file.assert_not_awaited()
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_handle_voice_message_reports_transcription_error(db_session_factory, allowed_user, monkeypatch):
    monkeypatch.setattr(
        free_chat, "transcribe_voice", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    update = make_voice_update(telegram_id=111)
    voice_file = MagicMock()
    voice_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw ogg bytes"))
    context = make_context()
    context.bot.get_file = AsyncMock(return_value=voice_file)

    await free_chat.handle_voice_message(update, context)

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")


@pytest.mark.asyncio
async def test_handle_voice_message_also_accepts_audio_file(
    db_session_factory, allowed_user, no_real_reply, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        free_chat,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.work, confidence=0.9)),
    )
    transcribe_mock = AsyncMock(return_value="отправить отчёт клиенту")
    monkeypatch.setattr(free_chat, "transcribe_voice", transcribe_mock)

    update = make_audio_update(telegram_id=111)
    audio_file = MagicMock()
    audio_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"raw mp3 bytes"))
    context = make_context()
    context.bot.get_file = AsyncMock(return_value=audio_file)

    await free_chat.handle_voice_message(update, context)

    context.bot.get_file.assert_awaited_once_with("audio-file-id")
    transcribe_mock.assert_awaited_once_with(b"raw mp3 bytes")


@pytest.mark.asyncio
async def test_handle_unsupported_message_replies_with_hint(db_session_factory, allowed_user):
    update = MagicMock()
    update.effective_user.id = 111
    update.message.reply_text = AsyncMock()

    await free_chat.handle_unsupported_message(update, make_context())

    update.message.reply_text.assert_awaited_once()
    assert "формат" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_handle_unsupported_message_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update = MagicMock()
    update.effective_user.id = 999
    update.message.reply_text = AsyncMock()

    await free_chat.handle_unsupported_message(update, make_context())

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_context_correction_sets_chosen_context_and_confirms(db_session_factory, allowed_user):
    with db_session_factory() as session:
        user = User(telegram_id=111, onboarding_completed=True)
        session.add(user)
        session.flush()
        note = Note(user_id=user.id, content="что-то", context=Context.work)
        session.add(note)
        session.commit()
        note_id = note.id

    update = MagicMock()
    update.callback_query.from_user.id = 111
    update.callback_query.data = f"set_context:{note_id}:personal"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await free_chat.handle_context_correction(update, context=None)

    with db_session_factory() as session:
        note = session.get(Note, note_id)
        assert note.context == Context.personal

    update.callback_query.answer.assert_awaited_once()
    assert "личное" in update.callback_query.answer.await_args.args[0]
    update.callback_query.edit_message_text.assert_not_called()


@pytest.mark.asyncio
async def test_context_correction_rejects_foreign_note(db_session_factory, allowed_user):
    with db_session_factory() as session:
        owner = User(telegram_id=111, onboarding_completed=True)
        session.add(owner)
        session.flush()
        note = Note(user_id=owner.id, content="приватное", context=Context.personal)
        session.add(note)
        session.commit()
        note_id = note.id

    update = MagicMock()
    update.callback_query.from_user.id = 222
    update.callback_query.data = f"set_context:{note_id}:work"
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()

    await free_chat.handle_context_correction(update, context=None)

    update.callback_query.edit_message_text.assert_not_called()
    with db_session_factory() as session:
        note = session.get(Note, note_id)
        assert note.context == Context.personal
