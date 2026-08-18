from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def create_schema() -> None:
    # Import models before create_all so SQLAlchemy knows which tables to create.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

