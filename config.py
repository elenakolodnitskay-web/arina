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

    @property
    def allowed_user_ids_list(self) -> list[int]:
        return [
            int(uid.strip())
            for uid in self.allowed_user_ids.split(",")
            if uid.strip()
        ]


settings = Settings()
