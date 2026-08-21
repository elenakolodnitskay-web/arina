import json
from unittest.mock import AsyncMock

import pytest

from db.models import Tariff
from llm import onboarding_greeting


@pytest.mark.asyncio
async def test_generate_onboarding_greeting_returns_text_and_tariff(monkeypatch):
    fake_complete = AsyncMock(
        return_value=json.dumps({"greeting": "Привет! Рада познакомиться.", "tariff": "secretary"})
    )
    monkeypatch.setattr(onboarding_greeting, "complete", fake_complete)

    greeting, tariff = await onboarding_greeting.generate_onboarding_greeting("домохозяйка, двое детей")

    assert greeting == "Привет! Рада познакомиться."
    assert tariff == Tariff.secretary
    messages = fake_complete.await_args.args[0]
    assert messages[1]["content"] == "домохозяйка, двое детей"
    assert "женского рода" in messages[0]["content"]


@pytest.mark.asyncio
async def test_generate_onboarding_greeting_parses_markdown_wrapped_json(monkeypatch):
    fake_complete = AsyncMock(
        return_value="```json\n" + json.dumps({"greeting": "Здравствуйте!", "tariff": "trusted"}) + "\n```"
    )
    monkeypatch.setattr(onboarding_greeting, "complete", fake_complete)

    greeting, tariff = await onboarding_greeting.generate_onboarding_greeting(
        "владелец small business, есть сотрудники и клиенты"
    )

    assert greeting == "Здравствуйте!"
    assert tariff == Tariff.trusted


@pytest.mark.asyncio
async def test_generate_onboarding_greeting_recommends_accountant(monkeypatch):
    fake_complete = AsyncMock(
        return_value=json.dumps({"greeting": "Отлично, буду вести учёт.", "tariff": "accountant"})
    )
    monkeypatch.setattr(onboarding_greeting, "complete", fake_complete)

    greeting, tariff = await onboarding_greeting.generate_onboarding_greeting("фрилансер, веду учёт доходов и трат")

    assert tariff == Tariff.accountant
