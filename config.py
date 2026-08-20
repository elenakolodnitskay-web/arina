from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": в проде .env также содержит POSTGRES_PASSWORD — переменную
    # для docker-compose (${POSTGRES_PASSWORD} в docker-compose.prod.yml), не поле
    # приложения. Без extra="ignore" pydantic-settings падает на "лишнем" поле.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str
    database_url: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_api_key: str
    fernet_key: str
    allowed_user_ids: str = ""
    # Единый часовой пояс для всех пользователей (не персональный) — упрощение для
    # MVP, аудитория закрытой беты русскоязычная (см. CLAUDE.md). Используется при
    # разборе формулировок задач ("напомни в 13:07" — по этому времени) и при показе
    # времени пользователю.
    timezone: str = "Europe/Moscow"
    # MAX (мессенджер) — необязательные, пусты по умолчанию: без токена вебхук-сервер
    # MAX просто не запускается (см. bot/main.py), остальной бот работает как раньше.
    max_bot_token: str = ""
    max_webhook_secret: str = ""
    max_webhook_port: int = 8091

    @property
    def allowed_user_ids_list(self) -> list[int]:
        return [
            int(uid.strip())
            for uid in self.allowed_user_ids.split(",")
            if uid.strip()
        ]


settings = Settings()
