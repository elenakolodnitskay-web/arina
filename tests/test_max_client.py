from unittest.mock import AsyncMock, MagicMock

import pytest

from max_bot import client


@pytest.mark.asyncio
async def test_send_message_posts_to_max_api(monkeypatch):
    fake_response = MagicMock()
    fake_response.raise_for_status = MagicMock()

    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=fake_response)

    monkeypatch.setattr(client, "httpx", MagicMock(AsyncClient=MagicMock(return_value=fake_client)))
    monkeypatch.setattr(client.settings, "max_bot_token", "test-max-token")

    await client.send_message(12345, "привет")

    fake_client.post.assert_awaited_once()
    call = fake_client.post.await_args
    assert call.args[0] == "/messages"
    assert call.kwargs["params"] == {"user_id": 12345}
    assert call.kwargs["headers"] == {"Authorization": "test-max-token"}
    assert call.kwargs["json"]["text"] == "привет"
    fake_response.raise_for_status.assert_called_once()
