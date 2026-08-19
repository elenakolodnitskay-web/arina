from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    telegram_bot_token: str
    database_url: str
    openrouter_base_url: str
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
