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
