from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import main


@pytest.mark.asyncio
async def test_on_startup_sets_russian_commands(monkeypatch):
    monkeypatch.setattr(main, "get_scheduler", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(main.settings, "max_bot_token", "")

    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    await main._on_startup(application)

    application.bot.set_my_commands.assert_awaited_once_with(main.BOT_COMMANDS)
    commands_by_name = {c.command: c.description for c in main.BOT_COMMANDS}
    assert set(commands_by_name) == {"start", "help", "task", "tasks", "document", "delete_my_data"}
    assert all(description for description in commands_by_name.values())


@pytest.mark.asyncio
async def test_on_startup_starts_scheduler(monkeypatch):
    scheduler = MagicMock()
    monkeypatch.setattr(main, "get_scheduler", MagicMock(return_value=scheduler))
    monkeypatch.setattr(main.settings, "max_bot_token", "")

    application = MagicMock()
    application.bot.set_my_commands = AsyncMock()

    await main._on_startup(application)

    scheduler.start.assert_called_once()


def test_build_application_registers_all_handlers(monkeypatch):
    monkeypatch.setattr(main.settings, "telegram_bot_token", "test-token")

    application = main.build_application()

    assert len(application.handlers[0]) > 0
