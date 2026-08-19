from unittest.mock import AsyncMock

import pytest

from db.models import Context
from llm import reply


@pytest.mark.asyncio
async def test_generate_reply_without_summary(monkeypatch):
    fake_complete = AsyncMock(return_value="Записал, помогу с этим.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    result = await reply.generate_reply("нужно подготовить отчёт", Context.work, None)

    assert result == "Записал, помогу с этим."
    messages = fake_complete.await_args.args[0]
    assert messages[1]["content"] == "нужно подготовить отчёт"
    assert "рабочее" in messages[0]["content"]
    assert "Краткое summary предыдущих разговоров" not in messages[0]["content"]


@pytest.mark.asyncio
async def test_generate_reply_includes_summary_when_present(monkeypatch):
    fake_complete = AsyncMock(return_value="Как обсуждали вчера, всё в силе.")
    monkeypatch.setattr(reply, "complete", fake_complete)

    result = await reply.generate_reply(
        "напомни про встречу", Context.personal, "вчера договорились встретиться в пятницу"
    )

    assert result == "Как обсуждали вчера, всё в силе."
    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "личное" in system_prompt
    assert "вчера договорились встретиться в пятницу" in system_prompt
