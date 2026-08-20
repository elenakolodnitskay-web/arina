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


@pytest.mark.asyncio
async def test_parse_task_prompt_uses_configured_timezone(monkeypatch):
    fake_complete = AsyncMock(
        return_value='{"title": "т", "due_at": "2026-08-20T18:00:00+03:00", "recurrence_rule": null}'
    )
    monkeypatch.setattr(tasks, "complete", fake_complete)

    parsed = await tasks.parse_task("что-то в 18:00")

    system_prompt = fake_complete.await_args.args[0][0]["content"]
    assert "+03:00" in system_prompt or "+03" in system_prompt

    # "+03:00" из ответа модели должно верно перевестись в 15:00 UTC — та же
    # абсолютная точка во времени, не то же число часов.
    assert parsed.due_at.utcoffset().total_seconds() == 3 * 3600
    assert parsed.due_at.astimezone(timezone.utc).hour == 15


@pytest.mark.asyncio
async def test_parse_task_recurring_local_hour_preserved(monkeypatch):
    raw = '{"title": "созвон", "due_at": null, "recurrence_rule": "0 9 * * 1"}'
    monkeypatch.setattr(tasks, "complete", AsyncMock(return_value=raw))

    parsed = await tasks.parse_task("каждый понедельник в 9 утра по Москве")

    # Само значение "0 9 * * 1" не содержит смещения — интерпретация как локального
    # времени происходит в core/scheduler.py при постановке в планировщик, не здесь.
    assert parsed.recurrence_rule == "0 9 * * 1"
