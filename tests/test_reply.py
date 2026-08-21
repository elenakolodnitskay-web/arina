from unittest.mock import AsyncMock

import pytest

from db.models import Context
from llm import reply


@pytest.mark.asyncio
async def test_generate_reply_without_recent_context(monkeypatch):
    fake_complete = AsyncMock(return_value="Записал, помогу с этим.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    result = await reply.generate_reply("нужно подготовить отчёт", Context.work, None)

    assert result == "Записал, помогу с этим."
    messages = fake_complete.await_args.args[0]
    assert messages[1]["content"] == "нужно подготовить отчёт"
    assert "рабочее" in messages[0]["content"]
    assert "Последние сообщения пользователя" not in messages[0]["content"]
    assert "О пользователе (из профиля)" not in messages[0]["content"]


@pytest.mark.asyncio
async def test_generate_reply_includes_recent_context_when_present(monkeypatch):
    fake_complete = AsyncMock(return_value="Как обсуждали вчера, всё в силе.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    result = await reply.generate_reply(
        "напомни про встречу", Context.personal, "вчера договорились встретиться в пятницу"
    )

    assert result == "Как обсуждали вчера, всё в силе."
    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "личное" in system_prompt
    assert "вчера договорились встретиться в пятницу" in system_prompt


@pytest.mark.asyncio
async def test_generate_reply_includes_profile_summary_when_present(monkeypatch):
    fake_complete = AsyncMock(return_value="Хорошо, учту.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    await reply.generate_reply(
        "что там по делам", Context.work, None, profile_summary="фрилансер, дизайн и seo-проекты"
    )

    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "фрилансер, дизайн и seo-проекты" in system_prompt


@pytest.mark.asyncio
async def test_generate_reply_omits_profile_block_when_absent(monkeypatch):
    fake_complete = AsyncMock(return_value="Хорошо.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    await reply.generate_reply("привет", Context.personal, None)

    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "О пользователе (из профиля)" not in system_prompt


@pytest.mark.asyncio
async def test_generate_reply_enables_web_search(monkeypatch):
    fake_complete = AsyncMock(return_value="В Симферополе сейчас +7.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    await reply.generate_reply("какая погода в Симферополе", Context.personal, None)

    assert fake_complete.await_args.kwargs["web_search"] is True


@pytest.mark.asyncio
async def test_generate_reply_includes_relevant_notes_when_present(monkeypatch):
    fake_complete = AsyncMock(return_value="Да, помню — ты говорил про это.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    await reply.generate_reply(
        "напомни, что там было с арендой",
        Context.personal,
        None,
        relevant_notes="месяц назад: договор аренды продлили до конца года",
    )

    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "договор аренды продлили до конца года" in system_prompt
    assert "не в недавней истории" in system_prompt


@pytest.mark.asyncio
async def test_generate_reply_omits_relevant_notes_block_when_absent(monkeypatch):
    fake_complete = AsyncMock(return_value="Хорошо.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    await reply.generate_reply("привет", Context.personal, None)

    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "не в недавней истории" not in system_prompt
