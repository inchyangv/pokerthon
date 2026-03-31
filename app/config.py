from datetime import datetime
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PORT: int = 8000
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pokerthon"
    ADMIN_PASSWORD: str = "changeme"
    APP_ENCRYPTION_KEY: str = "changeme_32_char_key_here_______"
    ACTION_TIMEOUT_SECONDS: int = 600
    TABLE_BUYIN: int = 40
    SMALL_BLIND: int = 1
    BIG_BLIND: int = 2

    # Tournament blind escalation
    # Set to ISO datetime string to enable auto escalation, e.g. "2026-04-01T10:00:00+09:00"
    TOURNAMENT_START_AT: datetime | None = None
    BLIND_LEVEL_HOURS: int = 48

    # Bot settings
    BOT_ENABLED: bool = True
    BOT_POLL_INTERVAL: float = 2.0
    BOT_ACTION_DELAY_MIN: float = 30.0
    BOT_ACTION_DELAY_MAX: float = 60.0
    BOT_AUTO_SEED: bool = False
    BOT_INITIAL_CHIPS: int = 1000
    BOT_AUTO_RESEAT: bool = True   # refill chips and reseat evicted bots
    BOT_RESEAT_CHIPS: int = 1000   # chips granted on each reseat

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
