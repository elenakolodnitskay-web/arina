from unittest.mock import AsyncMock

import pytest

from core import relay


@pytest.mark.asyncio
async def test_parse_relay_message_extracts_username_and_message(monkeypatch):
    raw = '{"username": "ivan_petrov", "message": "встреча переносится на пятницу"}'
    monkeypatch.setattr(relay, "complete", AsyncMock(return_value=raw))

    parsed = await relay.parse_relay_message("передай @ivan_petrov, что встреча переносится на пятницу")

    assert parsed.username == "ivan_petrov"
    assert parsed.message == "встреча переносится на пятницу"


@pytest.mark.asyncio
async def test_parse_relay_message_returns_none_username_without_at(monkeypatch):
    raw = '{"username": null, "message": "передай Ивану, что встреча переносится"}'
    monkeypatch.setattr(relay, "complete", AsyncMock(return_value=raw))

    parsed = await relay.parse_relay_message("передай Ивану, что встреча переносится")

    assert parsed.username is None


@pytest.mark.asyncio
async def test_parse_relay_message_raises_on_unparseable_response(monkeypatch):
    monkeypatch.setattr(relay, "complete", AsyncMock(return_value="непонятно что"))

    with pytest.raises(ValueError):
        await relay.parse_relay_message("что-то невнятное")
