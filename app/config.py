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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
