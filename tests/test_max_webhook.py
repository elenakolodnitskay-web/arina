from unittest.mock import AsyncMock

import pytest

from max_bot import webhook


@pytest.mark.asyncio
async def test_webhook_routes_message_created_to_handler(aiohttp_client, monkeypatch):
    mock_handle = AsyncMock()
    monkeypatch.setattr(webhook, "handle_text_message", mock_handle)
    monkeypatch.setattr(webhook.settings, "max_webhook_secret", "")

    app = webhook.build_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/webhook",
        json={
            "update_type": "message_created",
            "message": {"body": {"text": "привет"}, "sender": {"user_id": 42}},
        },
    )

    assert resp.status == 200
    mock_handle.assert_awaited_once_with(42, "привет")


@pytest.mark.asyncio
async def test_webhook_ignores_unknown_update_types(aiohttp_client, monkeypatch):
    mock_handle = AsyncMock()
    monkeypatch.setattr(webhook, "handle_text_message", mock_handle)
    monkeypatch.setattr(webhook.settings, "max_webhook_secret", "")

    app = webhook.build_app()
    client = await aiohttp_client(app)

    resp = await client.post("/webhook", json={"update_type": "message_callback"})

    assert resp.status == 200
    mock_handle.assert_not_called()


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(aiohttp_client, monkeypatch):
    mock_handle = AsyncMock()
    monkeypatch.setattr(webhook, "handle_text_message", mock_handle)
    monkeypatch.setattr(webhook.settings, "max_webhook_secret", "expected-secret")

    app = webhook.build_app()
    client = await aiohttp_client(app)

    resp = await client.post(
        "/webhook",
        json={"update_type": "message_created", "message": {}},
        headers={"X-Max-Bot-Api-Secret": "wrong"},
    )

    assert resp.status == 403
    mock_handle.assert_not_called()
