from config import Settings


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:password@localhost:5432/arina_test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("FERNET_KEY", "test-fernet-key")

    settings = Settings()
    assert settings.telegram_bot_token == "test-token"
    assert settings.database_url.startswith("postgresql://")


def test_allowed_user_ids_list_parses_csv():
    settings = Settings(allowed_user_ids="123, 456,789")
    assert settings.allowed_user_ids_list == [123, 456, 789]


def test_allowed_user_ids_list_empty_by_default():
    settings = Settings()
    assert settings.allowed_user_ids_list == []
