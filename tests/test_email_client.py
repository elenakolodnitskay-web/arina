from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from core import email_client


def make_fake_client(response):
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(return_value=response)
    return fake_client


@pytest.fixture(autouse=True)
def configured_settings(monkeypatch):
    monkeypatch.setattr(email_client.settings, "resend_api_key", "test-resend-key")
    monkeypatch.setattr(email_client.settings, "email_from_address", "Арина <arina@example.com>")


@pytest.mark.asyncio
async def test_send_email_posts_to_resend_api(monkeypatch):
    fake_response = MagicMock(status_code=200)
    fake_client = make_fake_client(fake_response)
    monkeypatch.setattr(email_client, "httpx", MagicMock(AsyncClient=MagicMock(return_value=fake_client)))

    await email_client.send_email("ivan@example.com", "Оплата", "Просрочен платёж.")

    fake_client.post.assert_awaited_once()
    call = fake_client.post.await_args
    assert call.args[0] == email_client.RESEND_API_URL
    assert call.kwargs["headers"] == {"Authorization": "Bearer test-resend-key"}
    assert call.kwargs["json"]["to"] == ["ivan@example.com"]
    assert call.kwargs["json"]["subject"] == "Оплата"
    assert call.kwargs["json"]["text"] == "Просрочен платёж."
    assert call.kwargs["json"]["from"] == "Арина <arina@example.com>"


@pytest.mark.asyncio
async def test_send_email_raises_on_api_error_status(monkeypatch):
    fake_response = MagicMock(status_code=422)
    fake_client = make_fake_client(fake_response)
    monkeypatch.setattr(email_client, "httpx", MagicMock(AsyncClient=MagicMock(return_value=fake_client)))

    with pytest.raises(email_client.EmailUnavailableError):
        await email_client.send_email("ivan@example.com", "Оплата", "Текст")


@pytest.mark.asyncio
async def test_send_email_raises_on_network_error(monkeypatch):
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_client.post = AsyncMock(side_effect=httpx.ConnectError("boom"))
    monkeypatch.setattr(email_client, "httpx", MagicMock(AsyncClient=MagicMock(return_value=fake_client)))

    with pytest.raises(email_client.EmailUnavailableError):
        await email_client.send_email("ivan@example.com", "Оплата", "Текст")


@pytest.mark.asyncio
async def test_send_email_raises_when_not_configured(monkeypatch):
    monkeypatch.setattr(email_client.settings, "resend_api_key", "")
    monkeypatch.setattr(email_client.settings, "email_from_address", "")

    with pytest.raises(email_client.EmailUnavailableError):
        await email_client.send_email("ivan@example.com", "Оплата", "Текст")
