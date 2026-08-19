from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from core import tasks


@pytest.mark.asyncio
async def test_parse_task_one_off_reminder(monkeypatch):
    raw = (
        '{"title": "позвонить маме", "due_at": "2026-08-20T15:00:00+00:00", '
        '"recurrence_rule": null}'
    )
    monkeypatch.setattr(tasks, "complete", AsyncMock(return_value=raw))

    parsed = await tasks.parse_task("позвонить маме завтра в 18:00")

    assert parsed.title == "позвонить маме"
    assert parsed.due_at == datetime(2026, 8, 20, 15, 0, tzinfo=timezone.utc)
    assert parsed.recurrence_rule is None


@pytest.mark.asyncio
async def test_parse_task_recurring_reminder(monkeypatch):
    raw = '{"title": "созвон с командой", "due_at": null, "recurrence_rule": "0 9 * * 1"}'
    monkeypatch.setattr(tasks, "complete", AsyncMock(return_value=raw))

    parsed = await tasks.parse_task("каждый понедельник в 9 созвон с командой")

    assert parsed.due_at is None
    assert parsed.recurrence_rule == "0 9 * * 1"


@pytest.mark.asyncio
async def test_parse_task_raises_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(tasks, "complete", AsyncMock(return_value="непонятно что"))

    with pytest.raises(ValueError):
        await tasks.parse_task("что-то невнятное")
