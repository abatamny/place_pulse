import os

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import delete


TEST_DATABASE_NAME = os.getenv("TEST_POSTGRES_DB", "placepulse_test")
os.environ["POSTGRES_DB"] = TEST_DATABASE_NAME


def ensure_test_database() -> None:
    with psycopg.connect(
        host=os.getenv("DB_HOST", "db"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname="postgres",
        user=os.getenv("POSTGRES_USER", "placepulse"),
        password=os.getenv("POSTGRES_PASSWORD", "placepulse"),
        autocommit=True,
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DATABASE_NAME,)
        ).fetchone()
        if exists is None:
            connection.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(TEST_DATABASE_NAME)
                )
            )


ensure_test_database()

from app.database import SessionLocal, create_schema  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AuthSession, User  # noqa: E402

create_schema()


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clean_auth_tables():
    def clean() -> None:
        with SessionLocal() as db:
            db.execute(delete(AuthSession))
            db.execute(delete(User))
            db.commit()

    clean()
    yield
    clean()

