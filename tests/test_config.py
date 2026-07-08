from roaring_kittens.config import Settings


def test_settings_reads_env_and_normalizes_db_url(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "42")
    monkeypatch.setenv("TINKOFF_TOKEN", "tink")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    # Railway выдаёт postgres:// — мы должны нормализовать в postgresql+asyncpg://
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/db")
    monkeypatch.setenv("FERNET_KEY", "k")
    s = Settings(_env_file=None)
    assert s.admin_telegram_id == 42
    assert s.database_url == "postgresql+asyncpg://u:p@h:5432/db"


def test_settings_admin_id_is_optional(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.delenv("ADMIN_TELEGRAM_ID", raising=False)
    monkeypatch.setenv("TINKOFF_TOKEN", "tink")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h:5432/db")
    monkeypatch.setenv("FERNET_KEY", "k")
    s = Settings(_env_file=None)
    assert s.admin_telegram_id is None  # владелец придёт через первый /start
