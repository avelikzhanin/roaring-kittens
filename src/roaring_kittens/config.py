from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    telegram_bot_token: str
    # Опционально: заранее фиксирует владельца. Если не задан — владельцем
    # становится первый пользователь, нажавший /start (owner-claim).
    admin_telegram_id: int | None = None
    tinkoff_token: str
    openai_api_key: str
    database_url: str
    fernet_key: str
    tz: str = "Europe/Moscow"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def normalize_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v
