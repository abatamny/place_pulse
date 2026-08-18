import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import URL


@dataclass(frozen=True)
class Settings:
    db_host: str = os.getenv("DB_HOST", "db")
    db_port: int = int(os.getenv("DB_PORT", "5432"))
    db_name: str = os.getenv("POSTGRES_DB", "placepulse")
    db_user: str = os.getenv("POSTGRES_USER", "placepulse")
    db_password: str = os.getenv("POSTGRES_PASSWORD", "placepulse")
    media_root: Path = Path(os.getenv("MEDIA_ROOT", "/app/media"))

    @property
    def database_url(self) -> URL:
        return URL.create(
            drivername="postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


settings = Settings()

