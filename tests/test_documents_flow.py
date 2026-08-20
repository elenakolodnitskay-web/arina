from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bot.handlers import documents_flow
from db.models import Base, Context, Note, User
from llm.classify import ClassificationResult
from llm.client import LLMUnavailableError
from llm.documents import ParsedDocument


@pytest.fixture()
def db_session_factory(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(documents_flow, "SessionLocal", factory)
    yield factory
    engine.dispose()


@pytest.fixture()
def allowed_user(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "allowed_user_ids", "111")


def make_command_update(telegram_id: int, args: list[str]):
    update = MagicMock()
    update.effective_user.id = telegram_id
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.args = args
    context.user_data = {}
    return update, context


def make_callback_update(telegram_id: int, callback_data: str, user_data: dict):
    update = MagicMock()
    update.callback_query.from_user.id = telegram_id
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.reply_document = AsyncMock()
    context = MagicMock()
    context.user_data = user_data
    return update, context


@pytest.mark.asyncio
async def test_create_document_without_description_prompts_usage(db_session_factory, allowed_user):
    update, context = make_command_update(111, [])

    await documents_flow.create_document(update, context)

    assert "/document" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_create_document_ignores_non_whitelisted_user(db_session_factory, allowed_user):
    update, context = make_command_update(999, ["письмо", "клиенту"])

    await documents_flow.create_document(update, context)

    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_create_document_prompts_start_for_unonboarded_user(db_session_factory, allowed_user):
    update, context = make_command_update(111, ["письмо", "клиенту"])

    await documents_flow.create_document(update, context)

    assert "/start" in update.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_create_document_generates_draft_and_stores_pending(
    db_session_factory, allowed_user, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    draft = ParsedDocument(format="docx", title="Письмо коллеге", content="Уважаемый коллега, ...")
    monkeypatch.setattr(documents_flow, "generate_document", AsyncMock(return_value=draft))

    update, context = make_command_update(111, ["письмо", "коллеге"])
    await documents_flow.create_document(update, context)

    assert context.user_data[documents_flow.PENDING_KEY] == draft
    assert "Уважаемый коллега, ..." in update.message.reply_text.await_args.args[0]
    assert "Word" in update.message.reply_text.await_args.args[0]
    assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_create_document_reports_llm_unavailable(db_session_factory, allowed_user, monkeypatch):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        documents_flow, "generate_document", AsyncMock(side_effect=LLMUnavailableError("сеть недоступна"))
    )

    update, context = make_command_update(111, ["письмо"])
    await documents_flow.create_document(update, context)

    update.message.reply_text.assert_awaited_once_with("сеть недоступна")
    assert documents_flow.PENDING_KEY not in context.user_data


@pytest.mark.asyncio
async def test_handle_confirm_document_without_pending_draft(db_session_factory, allowed_user):
    update, context = make_callback_update(111, documents_flow.CONFIRM_CALLBACK, {})

    await documents_flow.handle_confirm_document(update, context)

    update.callback_query.answer.assert_awaited_once()
    assert update.callback_query.answer.await_args.kwargs.get("show_alert") is True


@pytest.mark.asyncio
async def test_handle_confirm_document_saves_note_and_sends_file(
    db_session_factory, allowed_user, monkeypatch
):
    with db_session_factory() as session:
        session.add(User(telegram_id=111, onboarding_completed=True))
        session.commit()

    monkeypatch.setattr(
        documents_flow,
        "classify_message",
        AsyncMock(return_value=ClassificationResult(context=Context.work, confidence=0.85)),
    )
    build_mock = MagicMock(return_value=(b"fake docx bytes", "Письмо клиенту.docx"))
    monkeypatch.setattr(documents_flow, "build_document_file", build_mock)

    draft = ParsedDocument(format="docx", title="Письмо клиенту", content="Готовый черновик письма")
    update, context = make_callback_update(
        111, documents_flow.CONFIRM_CALLBACK, {documents_flow.PENDING_KEY: draft}
    )
    await documents_flow.handle_confirm_document(update, context)

    with db_session_factory() as session:
        note = session.query(Note).one()
        assert note.content == "Готовый черновик письма"
        assert note.context == Context.work

    assert documents_flow.PENDING_KEY not in context.user_data
    build_mock.assert_called_once_with("docx", "Письмо клиенту", "Готовый черновик письма")
    update.callback_query.edit_message_text.assert_awaited_once()
    update.callback_query.message.reply_document.assert_awaited_once()
    assert update.callback_query.message.reply_document.await_args.kwargs["filename"] == "Письмо клиенту.docx"


@pytest.mark.asyncio
async def test_handle_reformulate_document_clears_pending(db_session_factory, allowed_user):
    draft = ParsedDocument(format="docx", title="старый", content="старый черновик")
    update, context = make_callback_update(
        111, documents_flow.REFORMULATE_CALLBACK, {documents_flow.PENDING_KEY: draft}
    )

    await documents_flow.handle_reformulate_document(update, context)

    assert documents_flow.PENDING_KEY not in context.user_data
    update.callback_query.edit_message_text.assert_awaited_once()
    assert "/document" in update.callback_query.edit_message_text.await_args.args[0]


@pytest.mark.asyncio
async def test_start_document_draft_prompts_start_for_unonboarded_user(db_session_factory, allowed_user):
    update = MagicMock()
    update.effective_user.id = 111
    update.message.reply_text = AsyncMock()
    context = MagicMock()
    context.user_data = {}

    await documents_flow.start_document_draft(update, context, "письмо клиенту")

    assert "/start" in update.message.reply_text.await_args.args[0]
