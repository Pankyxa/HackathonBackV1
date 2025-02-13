from pydantic_settings import BaseSettings
import os
from pathlib import Path

# Получаем абсолютный путь к корневой директории проекта
BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    jwt_secret: str
    postgres_user: str
    postgres_password: str
    postgres_host: str
    postgres_port: str
    postgres_db: str

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@localhost:{self.postgres_port}/{self.postgres_db}"

    class Config:
        env_file = BASE_DIR / ".env"


settings = Settings()
